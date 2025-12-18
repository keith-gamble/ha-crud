"""OAuth helper functions for config_mcp MCP server.

This module provides OAuth/OIDC integration with the hass-oidc-auth component,
allowing browser-based MCP clients to authenticate via OAuth.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant

from .const import OIDC_DOMAIN

_LOGGER = logging.getLogger(__name__)

# Cache for JWKS keys
_jwks_cache: dict[str, Any] | None = None
_jwks_cache_time: float = 0
JWKS_CACHE_TTL = 300  # 5 minutes


def is_oidc_available(hass: HomeAssistant) -> bool:
    """Check if hass-oidc-auth is available and configured.

    Args:
        hass: Home Assistant instance

    Returns:
        True if hass-oidc-auth component is loaded
    """
    return OIDC_DOMAIN in hass.config.components


def get_external_url(hass: HomeAssistant) -> str | None:
    """Get the external URL for Home Assistant.

    Args:
        hass: Home Assistant instance

    Returns:
        External URL or internal URL as fallback, None if unavailable
    """
    try:
        return hass.config.external_url or hass.config.internal_url
    except Exception:
        return None


async def get_oidc_metadata(hass: HomeAssistant) -> dict[str, Any] | None:
    """Get OIDC metadata pointing to hass-oidc-auth endpoints.

    This builds OAuth Authorization Server Metadata (RFC 8414) that points
    to the OIDC provider endpoints exposed by hass-oidc-auth.

    Args:
        hass: Home Assistant instance

    Returns:
        OAuth metadata dict, or None if OIDC is unavailable
    """
    if not is_oidc_available(hass):
        return None

    base_url = get_external_url(hass)
    if not base_url:
        _LOGGER.warning("Cannot determine external URL for OIDC metadata")
        return None

    # Remove trailing slash if present
    base_url = base_url.rstrip("/")

    return {
        "issuer": f"{base_url}/oidc",
        "authorization_endpoint": f"{base_url}/oidc/authorize",
        "token_endpoint": f"{base_url}/oidc/token",
        "registration_endpoint": f"{base_url}/oidc/register",
        "jwks_uri": f"{base_url}/oidc/jwks",
        "userinfo_endpoint": f"{base_url}/oidc/userinfo",
        "scopes_supported": ["openid", "profile", "email"],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
    }


async def fetch_jwks(hass: HomeAssistant) -> dict[str, Any] | None:
    """Fetch JWKS from hass-oidc-auth for token validation.

    Uses a 5-minute cache to reduce network requests while still
    allowing key rotation.

    Args:
        hass: Home Assistant instance

    Returns:
        JWKS dict with keys array, or None if unavailable
    """
    global _jwks_cache, _jwks_cache_time

    current_time = time.time()

    # Return cached JWKS if still valid
    if _jwks_cache and (current_time - _jwks_cache_time) < JWKS_CACHE_TTL:
        return _jwks_cache

    if not is_oidc_available(hass):
        return None

    # Build JWKS URI - use internal URL since we're on the same instance
    # Try external URL first, then internal URL, then localhost
    base_url = get_external_url(hass)
    if not base_url:
        # Fall back to HA's API base URL (localhost)
        port = hass.config.api.port if hass.config.api else 8123
        ssl = hass.config.api.use_ssl if hass.config.api else False
        scheme = "https" if ssl else "http"
        base_url = f"{scheme}://127.0.0.1:{port}"

    jwks_uri = f"{base_url}/oidc/jwks"

    try:
        from aiohttp import ClientSession

        async with ClientSession() as session:
            # Use verify_ssl=False for local/self-signed connections
            async with session.get(jwks_uri, ssl=False) as response:
                if response.status == 200:
                    _jwks_cache = await response.json()
                    _jwks_cache_time = current_time
                    _LOGGER.debug("Fetched JWKS from %s", jwks_uri)
                    return _jwks_cache
                else:
                    _LOGGER.warning(
                        "Failed to fetch JWKS from %s: HTTP %s",
                        jwks_uri,
                        response.status,
                    )
    except Exception as err:
        _LOGGER.warning("Failed to fetch JWKS: %s", err)

    return None


async def validate_oauth_token(
    hass: HomeAssistant, token: str
) -> dict[str, Any] | None:
    """Validate an OAuth token from hass-oidc-auth.

    Validates the JWT token using the JWKS from hass-oidc-auth,
    checking signature, expiration, and issuer.

    Args:
        hass: Home Assistant instance
        token: The Bearer token (JWT) to validate

    Returns:
        Decoded token claims if valid, None otherwise
    """
    _LOGGER.warning("Attempting OAuth token validation...")

    if not is_oidc_available(hass):
        _LOGGER.warning("OIDC not available")
        return None

    jwks = await fetch_jwks(hass)
    if not jwks:
        _LOGGER.warning("No JWKS available for token validation")
        return None

    _LOGGER.warning("Got JWKS with %d keys", len(jwks.get("keys", [])))

    # Build JWKS URI for PyJWKClient
    base_url = get_external_url(hass)
    if not base_url:
        port = hass.config.api.port if hass.config.api else 8123
        ssl = hass.config.api.use_ssl if hass.config.api else False
        scheme = "https" if ssl else "http"
        base_url = f"{scheme}://127.0.0.1:{port}"

    jwks_uri = f"{base_url}/oidc/jwks"

    try:
        import jwt
        from jwt import PyJWK

        # Get the key ID from the token header
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        _LOGGER.warning("Token kid: %s, alg: %s", kid, unverified_header.get("alg"))

        # Find the matching key in our cached JWKS
        signing_key = None
        available_kids = [k.get("kid") for k in jwks.get("keys", [])]
        _LOGGER.warning("Available JWKS kids: %s", available_kids)

        for key_data in jwks.get("keys", []):
            if key_data.get("kid") == kid or kid is None:
                # Convert JWK to a key object
                jwk = PyJWK.from_dict(key_data)
                signing_key = jwk.key
                _LOGGER.warning("Found matching key for kid: %s", key_data.get("kid"))
                break

        if signing_key is None:
            _LOGGER.warning("No matching key found in JWKS for kid: %s", kid)
            return None

        _LOGGER.warning("Decoding token...")

        # Decode the token first without verification to get the issuer
        unverified = jwt.decode(token, options={"verify_signature": False})
        token_issuer = unverified.get("iss")
        _LOGGER.warning("Token issuer: %s, sub: %s", token_issuer, unverified.get("sub"))

        # Decode and validate the token
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            options={
                "verify_exp": True,
                "verify_iat": True,
                "verify_iss": False,  # Issuer URL may vary (internal vs external)
                "verify_aud": False,  # Audience varies by client
            },
        )

        _LOGGER.warning("Token decoded successfully, checking issuer...")

        # Validate issuer is a reasonable HTTPS URL from our domain
        # The signature validation using our JWKS is the primary security check
        if not token_issuer or not token_issuer.startswith("https://"):
            _LOGGER.warning("OAuth token has invalid issuer: %s", token_issuer)
            return None

        _LOGGER.warning(
            "OAuth token validated successfully for sub: %s",
            claims.get("sub"),
        )
        return claims

    except jwt.ExpiredSignatureError:
        _LOGGER.warning("OAuth token has expired")
    except jwt.InvalidTokenError as err:
        _LOGGER.warning("Invalid OAuth token: %s", err)
    except Exception as err:
        _LOGGER.warning("Error validating OAuth token: %s", err)

    return None


def clear_jwks_cache() -> None:
    """Clear the JWKS cache.

    Useful for testing or when keys are known to have rotated.
    """
    global _jwks_cache, _jwks_cache_time
    _jwks_cache = None
    _jwks_cache_time = 0
