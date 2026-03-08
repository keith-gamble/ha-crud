"""HTTP views for MCP (Model Context Protocol) transport.

This module provides HTTP endpoints that implement the MCP Streamable HTTP
transport protocol, allowing MCP clients to connect to the config_mcp MCP server.

The implementation follows Home Assistant's mcp_server component pattern,
using anyio memory streams to bridge HTTP transport with the MCP SDK.

OAuth Support:
When hass-oidc-auth is installed and OAuth is enabled, this module also
provides an OAuth metadata endpoint for browser-based MCP clients to
discover authentication endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

import anyio
from aiohttp import web
from mcp.server import Server
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import API_BASE_PATH_MCP, OAUTH_METADATA_PATH
from .mcp_server import create_mcp_server

_LOGGER = logging.getLogger(__name__)

# Request timeout in seconds
REQUEST_TIMEOUT = 120


@dataclass
class Streams:
    """Paired streams for MCP communication.

    The MCP server reads from read_stream and writes to write_stream.
    HTTP handlers write to read_stream_writer and read from write_stream_reader.
    """

    read_stream: anyio.abc.ObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: anyio.abc.ObjectSendStream[SessionMessage | Exception]
    write_stream: anyio.abc.ObjectSendStream[SessionMessage]
    write_stream_reader: anyio.abc.ObjectReceiveStream[SessionMessage]


def create_streams() -> Streams:
    """Create paired memory streams for MCP communication."""
    # Client -> Server stream
    read_stream_writer, read_stream = anyio.create_memory_object_stream[
        SessionMessage | Exception
    ](max_buffer_size=1)

    # Server -> Client stream
    write_stream, write_stream_reader = anyio.create_memory_object_stream[
        SessionMessage
    ](max_buffer_size=1)

    return Streams(
        read_stream=read_stream,
        read_stream_writer=read_stream_writer,
        write_stream=write_stream,
        write_stream_reader=write_stream_reader,
    )


class MCPOAuthMetadataView(HomeAssistantView):
    """View providing OAuth metadata for MCP clients.

    This allows MCP clients to discover OAuth endpoints when
    hass-oidc-auth is available. The metadata points to the OIDC
    provider endpoints for authorization, token exchange, and
    dynamic client registration.

    Endpoint: /.well-known/oauth-authorization-server/config_mcp/mcp
    """

    url = OAUTH_METADATA_PATH
    name = "api:config_mcp:mcp:oauth_metadata"
    requires_auth = False  # Must be public for OAuth discovery

    def __init__(self, hass: HomeAssistant):
        """Initialize the view."""
        self._hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - return OAuth metadata.

        Returns OAuth Authorization Server Metadata (RFC 8414) pointing
        to the hass-oidc-auth endpoints.
        """
        from .oauth import is_oidc_available

        if not is_oidc_available(self._hass):
            return web.json_response(
                {"error": "OAuth not available - hass-oidc-auth not configured"},
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )

        # Get base URL from request (same approach as OIDC provider)
        base_url = self._get_base_url_from_request(request)
        if not base_url:
            return web.json_response(
                {"error": "Could not determine base URL"},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

        # Build OAuth metadata pointing to OIDC provider endpoints
        metadata = {
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

        return web.json_response(metadata)

    def _get_base_url_from_request(self, request: web.Request) -> str | None:
        """Get the base URL from the request.

        Tries to determine the external URL from request headers,
        falling back to the Host header.
        """
        # Check for forwarded headers (reverse proxy)
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "https")
        forwarded_host = request.headers.get("X-Forwarded-Host")

        if forwarded_host:
            return f"{forwarded_proto}://{forwarded_host}"

        # Fall back to Host header
        host = request.headers.get("Host")
        if host:
            # Determine scheme from request
            scheme = "https" if request.secure else "http"
            return f"{scheme}://{host}"

        return None


class MCPStreamableView(HomeAssistantView):
    """View implementing MCP Streamable HTTP transport with OAuth support.

    This provides a stateless HTTP endpoint where each request creates
    a fresh MCP server instance, processes one message, and returns
    the response.

    Authentication:
    - When oauth_enabled=False: Uses standard HA Bearer token auth
    - When oauth_enabled=True: Accepts both HA tokens AND OAuth JWTs from hass-oidc-auth
    """

    url = API_BASE_PATH_MCP
    name = "api:config_mcp:mcp"
    requires_auth = False  # We handle auth ourselves for OAuth flexibility

    def __init__(self, hass: HomeAssistant, oauth_enabled: bool = False):
        """Initialize the view.

        Args:
            hass: Home Assistant instance
            oauth_enabled: Whether to accept OAuth tokens from hass-oidc-auth
        """
        self._hass = hass
        self._oauth_enabled = oauth_enabled

    async def _validate_request(self, request: web.Request) -> tuple[bool, str | None]:
        """Validate the request authentication.

        Tries HA's built-in token validation first, then OAuth if enabled.

        Args:
            request: The incoming request

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Get authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return False, "Missing or invalid Authorization header"

        token = auth_header[7:]  # Strip "Bearer " prefix

        # First, try standard HA long-lived access token validation
        try:
            # Validate as a long-lived access token (sync method despite async_ prefix)
            refresh_token = self._hass.auth.async_validate_access_token(token)
            if refresh_token is not None:
                _LOGGER.debug("Request authenticated via HA access token")
                return True, None
        except Exception as err:
            _LOGGER.debug("HA token validation failed: %s", err)

        # If OAuth is enabled, try OAuth token validation
        if self._oauth_enabled:
            from .oauth import validate_oauth_token

            claims = await validate_oauth_token(self._hass, token)
            if claims is not None:
                # Store claims in request for potential use
                request["oauth_claims"] = claims
                _LOGGER.debug("Request authenticated via OAuth token")
                return True, None

        return False, "Invalid authentication token"

    def _get_base_url_from_request(self, request: web.Request) -> str | None:
        """Get the base URL from the request."""
        forwarded_proto = request.headers.get("X-Forwarded-Proto", "https")
        forwarded_host = request.headers.get("X-Forwarded-Host")
        if forwarded_host:
            return f"{forwarded_proto}://{forwarded_host}"
        host = request.headers.get("Host")
        if host:
            scheme = "https" if request.secure else "http"
            return f"{scheme}://{host}"
        return None

    async def get(self, request: web.Request) -> web.Response:
        """Handle GET request - SSE endpoint for MCP Streamable HTTP.

        The MCP Streamable HTTP spec defines GET for server-to-client SSE
        streaming. This stateless implementation doesn't support persistent
        SSE sessions, so we return 405 with a helpful message. Clients
        should use POST for all request/response interactions.
        """
        # Validate authentication first
        is_valid, error = await self._validate_request(request)
        if not is_valid:
            return self.json_message(
                error or "Unauthorized",
                HTTPStatus.UNAUTHORIZED,
            )

        # SSE streaming not supported in stateless mode
        return web.json_response(
            {
                "jsonrpc": "2.0",
                "error": {
                    "code": -32000,
                    "message": "SSE streaming not supported. Use POST for requests.",
                },
            },
            status=HTTPStatus.OK,
        )

    async def post(self, request: web.Request) -> web.Response:
        """Handle POST request - process a JSON-RPC message.

        Each request creates a new MCP server instance, sends the message,
        waits for a response, and returns it.
        """
        # Validate authentication
        is_valid, error = await self._validate_request(request)
        if not is_valid:
            # If OAuth is enabled, include WWW-Authenticate header with metadata location
            if self._oauth_enabled:
                base_url = self._get_base_url_from_request(request)
                if base_url:
                    # RFC 9728 - OAuth 2.0 Protected Resource Metadata
                    metadata_url = f"{base_url}/.well-known/oauth-authorization-server/oidc"
                    return web.json_response(
                        {"message": error or "Unauthorized"},
                        status=HTTPStatus.UNAUTHORIZED,
                        headers={
                            "WWW-Authenticate": f'Bearer resource_metadata="{metadata_url}"',
                        },
                    )
            return self.json_message(
                error or "Unauthorized",
                HTTPStatus.UNAUTHORIZED,
            )

        try:
            body = await request.json()
        except (ValueError, json.JSONDecodeError):
            return self.json_message(
                "Invalid JSON in request body",
                HTTPStatus.BAD_REQUEST,
            )

        # Validate JSON-RPC structure
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
            return self.json_message(
                "Invalid JSON-RPC message",
                HTTPStatus.BAD_REQUEST,
            )

        try:
            # Create the MCP server
            server = create_mcp_server(self._hass)
            _LOGGER.debug("MCP server created for request")

            # Get initialization options (run in executor to avoid blocking)
            init_options = await self._hass.async_add_executor_job(
                server.create_initialization_options
            )

            # Create streams for this request
            streams = create_streams()

            # Parse the incoming message
            message = _parse_message(body)

            async with asyncio.timeout(REQUEST_TIMEOUT):
                try:
                    async with anyio.create_task_group() as tg:
                        # Start the server in the background (stateless mode)
                        async def run_server() -> None:
                            try:
                                await server.run(
                                    streams.read_stream,
                                    streams.write_stream,
                                    init_options,
                                    raise_exceptions=True,
                                    stateless=True,
                                )
                            except anyio.EndOfStream:
                                _LOGGER.debug("MCP server: read stream ended")
                            except anyio.ClosedResourceError:
                                _LOGGER.debug("MCP server: stream closed")
                            except Exception as e:
                                _LOGGER.debug("MCP server ended: %s", e)

                        tg.start_soon(run_server)

                        # Send the message to the server (wrapped in SessionMessage)
                        session_message = SessionMessage(message=message)
                        _LOGGER.debug("Sending message to MCP server")
                        await streams.read_stream_writer.send(session_message)
                        _LOGGER.debug("Message sent to MCP server")

                        # Wait for response (only for requests, not notifications)
                        if "id" in body:
                            _LOGGER.debug("Waiting for response from MCP server")
                            response_session_msg = await streams.write_stream_reader.receive()
                            _LOGGER.debug("Response received from MCP server")
                            # Server will exit naturally now that input is closed;
                            # cancel scope to unblock task group exit
                            tg.cancel_scope.cancel()
                            return web.json_response(
                                _serialize_message(response_session_msg.message)
                            )
                        else:
                            # Notification - no response expected
                            tg.cancel_scope.cancel()
                            return web.Response(status=HTTPStatus.ACCEPTED)
                finally:
                    # Ensure all stream endpoints are closed to prevent
                    # resource leaks, even if an exception occurred
                    for stream in (
                        streams.read_stream_writer,
                        streams.read_stream,
                        streams.write_stream,
                        streams.write_stream_reader,
                    ):
                        try:
                            await stream.aclose()
                        except Exception:
                            pass
                    _LOGGER.debug("All MCP streams closed")

        except asyncio.TimeoutError:
            return self.json_message(
                "Request timeout",
                HTTPStatus.GATEWAY_TIMEOUT,
            )
        except Exception as e:
            _LOGGER.exception("Error processing MCP request: %s", e)
            return self.json_message(
                f"Internal error: {e}",
                HTTPStatus.INTERNAL_SERVER_ERROR,
            )


def _parse_message(data: dict[str, Any]) -> JSONRPCMessage:
    """Parse a JSON-RPC message from raw data.

    Args:
        data: The raw message dict

    Returns:
        Parsed JSONRPCMessage (with root wrapper)
    """
    from pydantic import TypeAdapter

    # Use TypeAdapter to properly parse into JSONRPCMessage with root wrapper
    adapter = TypeAdapter(JSONRPCMessage)
    return adapter.validate_python(data)


def _serialize_message(message: JSONRPCMessage) -> dict[str, Any]:
    """Serialize a JSONRPCMessage to a dict for JSON response.

    Args:
        message: The message to serialize

    Returns:
        Dict representation
    """
    if hasattr(message, "model_dump"):
        return message.model_dump(exclude_none=True, by_alias=True)
    elif hasattr(message, "dict"):
        return message.dict(exclude_none=True, by_alias=True)
    else:
        # Fallback
        return {
            "jsonrpc": "2.0",
            "id": getattr(message, "id", None),
            "result": getattr(message, "result", None),
            "error": getattr(message, "error", None),
        }
