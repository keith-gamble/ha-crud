# Test Plan: Home Assistant Helpers Feature

**Feature Branch:** `feature/issue-3-helper-support`
**Version:** 1.3.0
**Date:** 2026-01-17

## Overview

This test plan covers the implementation of helper entity management via the hass-configuration-mcp component. The feature adds support for 7 helper types through both MCP tools and REST API endpoints.

### Supported Helper Domains

| Domain | Entity Type | Key Fields |
|--------|-------------|------------|
| `input_boolean` | Toggle switch | `name`, `icon`, `initial` |
| `input_number` | Numeric input | `name`, `min`, `max`, `step`, `mode`, `unit_of_measurement`, `initial` |
| `input_text` | Text input | `name`, `min`, `max`, `pattern`, `mode`, `initial` |
| `input_select` | Dropdown | `name`, `options`, `icon`, `initial` |
| `input_datetime` | Date/time picker | `name`, `has_date`, `has_time`, `icon`, `initial` |
| `counter` | Counter | `name`, `initial`, `step`, `minimum`, `maximum`, `icon` |
| `timer` | Timer | `name`, `duration`, `icon`, `restore` |

### WebSocket API Pattern

All helper domains follow this pattern:
- `{domain}/list` - List all helpers of a domain
- `{domain}/create` - Create a new helper
- `{domain}/update` - Update existing helper (requires `{domain}_id`)
- `{domain}/delete` - Delete a helper (requires `{domain}_id`)

---

## 1. Unit Tests

### 1.1 Permission Checking

**Test File:** `tests/unit/test_helpers_permissions.py`

| Test ID | Test Case | Expected Result |
|---------|-----------|-----------------|
| `test_read_permission_required` | Call list/get helper with `helpers_read: false` | `PermissionError` raised |
| `test_create_permission_required` | Call create helper with `helpers_create: false` | `PermissionError` raised |
| `test_update_permission_required` | Call update helper with `helpers_update: false` | `PermissionError` raised |
| `test_delete_permission_required` | Call delete helper with `helpers_delete: false` | `PermissionError` raised |
| `test_read_allowed_when_enabled` | Call list/get helper with `helpers_read: true` | Success |
| `test_create_allowed_when_enabled` | Call create helper with `helpers_create: true` | Success |
| `test_admin_required_for_create` | Non-admin user calls create | `401 Unauthorized` |
| `test_admin_required_for_update` | Non-admin user calls update | `401 Unauthorized` |
| `test_admin_required_for_delete` | Non-admin user calls delete | `401 Unauthorized` |

```python
# Example test structure
import pytest
from unittest.mock import Mock, AsyncMock, patch

@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock()
    hass.data = {"config_mcp": {"entry_id": {}}}
    return hass

@pytest.fixture
def mock_config_entry():
    """Create a mock config entry with default options."""
    entry = Mock()
    entry.options = {
        "helpers_read": False,
        "helpers_create": False,
        "helpers_update": False,
        "helpers_delete": False,
    }
    return entry

class TestHelperPermissions:
    """Test permission checking for helper operations."""

    async def test_read_permission_required(self, mock_hass, mock_config_entry):
        """Test that read permission is required to list helpers."""
        mock_config_entry.options["helpers_read"] = False

        with pytest.raises(PermissionError) as exc_info:
            await list_helpers(mock_hass, {"domain": "input_boolean"})

        assert "helpers_read" in str(exc_info.value)

    async def test_create_requires_admin(self, mock_hass):
        """Test that only admin users can create helpers."""
        mock_request = Mock()
        mock_request.get.return_value = Mock(is_admin=False)

        response = await HelperListView().post(mock_request)

        assert response.status == 401
```

### 1.2 Input Validation

**Test File:** `tests/unit/test_helpers_validation.py`

| Test ID | Test Case | Expected Result |
|---------|-----------|-----------------|
| `test_input_boolean_valid` | Valid input_boolean data | Success |
| `test_input_boolean_invalid_initial` | `initial: "invalid"` | `ValueError` |
| `test_input_number_min_max_valid` | `min: 0, max: 100` | Success |
| `test_input_number_min_greater_than_max` | `min: 100, max: 0` | `ValueError: min must be less than max` |
| `test_input_number_step_invalid` | `step: 0` or `step: -1` | `ValueError` |
| `test_input_number_initial_out_of_range` | `initial: 150, max: 100` | `ValueError` |
| `test_input_text_max_length_valid` | `max: 255` | Success |
| `test_input_text_min_greater_than_max` | `min: 50, max: 10` | `ValueError` |
| `test_input_text_invalid_pattern` | `pattern: "["` (invalid regex) | `ValueError` |
| `test_input_select_options_required` | Missing `options` field | `ValueError` |
| `test_input_select_empty_options` | `options: []` | `ValueError` |
| `test_input_select_invalid_initial` | `initial: "not_in_options"` | `ValueError` |
| `test_input_datetime_no_date_or_time` | `has_date: false, has_time: false` | `ValueError` |
| `test_counter_valid_config` | Valid counter config | Success |
| `test_counter_minimum_greater_than_maximum` | `minimum: 100, maximum: 0` | `ValueError` |
| `test_timer_valid_duration` | `duration: "00:05:00"` | Success |
| `test_timer_invalid_duration_format` | `duration: "invalid"` | `ValueError` |
| `test_domain_invalid` | `domain: "invalid_domain"` | `ValueError` |
| `test_name_required` | Missing `name` field | `ValueError` |
| `test_name_empty` | `name: ""` | `ValueError` |

```python
class TestInputNumberValidation:
    """Test input_number specific validation."""

    @pytest.mark.parametrize("min_val,max_val,expected", [
        (0, 100, True),
        (0.0, 1.0, True),
        (-100, 100, True),
        (100, 0, False),  # min > max
        (50, 50, True),   # min == max is valid
    ])
    async def test_min_max_validation(self, min_val, max_val, expected):
        """Test min/max value validation."""
        data = {"name": "test", "min": min_val, "max": max_val}

        if expected:
            result = validate_input_number(data)
            assert result["min"] == min_val
        else:
            with pytest.raises(ValueError) as exc:
                validate_input_number(data)
            assert "min" in str(exc.value) and "max" in str(exc.value)

    async def test_step_must_be_positive(self):
        """Test that step must be a positive number."""
        with pytest.raises(ValueError):
            validate_input_number({
                "name": "test",
                "min": 0,
                "max": 100,
                "step": -1
            })
```

### 1.3 Error Handling

**Test File:** `tests/unit/test_helpers_errors.py`

| Test ID | Test Case | Expected Result |
|---------|-----------|-----------------|
| `test_helper_not_found` | Get non-existent helper | `ValueError: Helper not found` |
| `test_duplicate_helper_name` | Create helper with existing name | `ValueError: already exists` |
| `test_websocket_error_handling` | WebSocket returns error | Proper error message returned |
| `test_connection_timeout` | WebSocket call times out | Graceful timeout handling |
| `test_invalid_json_body` | POST with invalid JSON | `400 Bad Request` |
| `test_missing_required_fields` | POST missing required fields | `400 Bad Request` with field list |

```python
class TestHelperErrors:
    """Test error handling for helper operations."""

    async def test_helper_not_found(self, mock_hass):
        """Test getting a non-existent helper."""
        mock_hass.connection.send_message = AsyncMock(
            return_value={"success": False, "error": {"code": "not_found"}}
        )

        with pytest.raises(ValueError) as exc:
            await get_helper(mock_hass, {"helper_id": "input_boolean.nonexistent"})

        assert "not found" in str(exc.value).lower()

    async def test_duplicate_name_error(self, mock_hass):
        """Test creating a helper with duplicate name."""
        mock_hass.connection.send_message = AsyncMock(
            return_value={"success": False, "error": {"code": "duplicate_name"}}
        )

        with pytest.raises(ValueError) as exc:
            await create_helper(mock_hass, {
                "domain": "input_boolean",
                "name": "Existing Helper"
            })

        assert "already exists" in str(exc.value).lower()
```

---

## 2. Integration Tests

### 2.1 List Helpers

**Test File:** `tests/integration/test_helpers_list.py`

| Test ID | Domain | Expected Result |
|---------|--------|-----------------|
| `test_list_input_booleans` | `input_boolean` | Returns array of input_boolean helpers |
| `test_list_input_numbers` | `input_number` | Returns array with min/max/step fields |
| `test_list_input_texts` | `input_text` | Returns array with pattern/mode fields |
| `test_list_input_selects` | `input_select` | Returns array with options field |
| `test_list_input_datetimes` | `input_datetime` | Returns array with has_date/has_time |
| `test_list_counters` | `counter` | Returns array with step/min/max fields |
| `test_list_timers` | `timer` | Returns array with duration/restore fields |
| `test_list_all_helpers` | All domains | Returns combined array with domain info |
| `test_list_empty_domain` | Domain with no helpers | Returns empty array |

```python
@pytest.mark.integration
class TestListHelpers:
    """Integration tests for listing helpers."""

    async def test_list_input_booleans(self, hass):
        """Test listing all input_boolean helpers."""
        result = await list_helpers(hass, {"domain": "input_boolean"})

        assert isinstance(result, list)
        for helper in result:
            assert "id" in helper
            assert "name" in helper
            assert helper.get("domain") == "input_boolean"

    async def test_list_all_helpers_no_filter(self, hass):
        """Test listing all helpers without domain filter."""
        result = await list_helpers(hass, {})

        assert isinstance(result, list)
        # Should include all domains
        domains = {h["domain"] for h in result}
        expected_domains = {
            "input_boolean", "input_number", "input_text",
            "input_select", "input_datetime", "counter", "timer"
        }
        # At least some domains should be present (may be empty)
        assert len(result) >= 0
```

### 2.2 CRUD Lifecycle Tests

**Test File:** `tests/integration/test_helpers_crud.py`

For each domain, test the full lifecycle:

```python
@pytest.mark.integration
@pytest.mark.parametrize("domain,create_data,update_data", [
    (
        "input_boolean",
        {"name": "Test Boolean", "icon": "mdi:toggle-switch"},
        {"name": "Updated Boolean", "initial": True}
    ),
    (
        "input_number",
        {"name": "Test Number", "min": 0, "max": 100, "step": 1, "mode": "slider"},
        {"name": "Updated Number", "min": 0, "max": 200, "initial": 50}
    ),
    (
        "input_text",
        {"name": "Test Text", "min": 0, "max": 100, "mode": "text"},
        {"name": "Updated Text", "pattern": "[a-z]+"}
    ),
    (
        "input_select",
        {"name": "Test Select", "options": ["opt1", "opt2", "opt3"]},
        {"name": "Updated Select", "options": ["new1", "new2"], "initial": "new1"}
    ),
    (
        "input_datetime",
        {"name": "Test DateTime", "has_date": True, "has_time": True},
        {"name": "Updated DateTime", "has_date": True, "has_time": False}
    ),
    (
        "counter",
        {"name": "Test Counter", "initial": 0, "step": 1},
        {"name": "Updated Counter", "minimum": 0, "maximum": 100}
    ),
    (
        "timer",
        {"name": "Test Timer", "duration": "00:05:00"},
        {"name": "Updated Timer", "duration": "00:10:00", "restore": True}
    ),
])
class TestHelperCRUDLifecycle:
    """Test full CRUD lifecycle for each helper domain."""

    async def test_create_helper(self, hass, domain, create_data, update_data):
        """Test creating a helper."""
        result = await create_helper(hass, {"domain": domain, **create_data})

        assert "id" in result
        assert result["name"] == create_data["name"]

        # Store ID for subsequent tests
        self.helper_id = result["id"]

        return result["id"]

    async def test_get_created_helper(self, hass, domain, create_data, update_data):
        """Test getting the created helper."""
        helper_id = await self.test_create_helper(hass, domain, create_data, update_data)

        result = await get_helper(hass, {"helper_id": helper_id})

        assert result["id"] == helper_id
        assert result["name"] == create_data["name"]

    async def test_update_helper(self, hass, domain, create_data, update_data):
        """Test updating the helper."""
        helper_id = await self.test_create_helper(hass, domain, create_data, update_data)

        result = await update_helper(hass, {
            "helper_id": helper_id,
            **update_data
        })

        assert result["name"] == update_data["name"]

    async def test_verify_entity_created(self, hass, domain, create_data, update_data):
        """Test that entity is created in Home Assistant."""
        helper_id = await self.test_create_helper(hass, domain, create_data, update_data)

        # Wait for entity to be registered
        await asyncio.sleep(0.5)

        entity_id = f"{domain}.{helper_id}"
        state = hass.states.get(entity_id)

        assert state is not None, f"Entity {entity_id} not found"

    async def test_delete_helper(self, hass, domain, create_data, update_data):
        """Test deleting the helper."""
        helper_id = await self.test_create_helper(hass, domain, create_data, update_data)

        result = await delete_helper(hass, {"helper_id": helper_id})

        assert result.get("deleted") == helper_id

        # Verify entity is removed
        await asyncio.sleep(0.5)
        entity_id = f"{domain}.{helper_id}"
        state = hass.states.get(entity_id)
        assert state is None, f"Entity {entity_id} still exists after deletion"
```

---

## 3. MCP Tool Tests

### 3.1 ha_list_helpers

**Test File:** `tests/mcp/test_mcp_list_helpers.py`

| Test ID | Arguments | Expected Result |
|---------|-----------|-----------------|
| `test_list_all_helpers` | `{}` | Array of all helpers across all domains |
| `test_list_by_domain` | `{"domain": "input_boolean"}` | Only input_boolean helpers |
| `test_list_invalid_domain` | `{"domain": "invalid"}` | `ValueError` |
| `test_list_empty_result` | Domain with no helpers | Empty array `[]` |
| `test_list_includes_metadata` | `{}` | Each helper has id, name, domain, icon |

```python
@pytest.mark.mcp
class TestMCPListHelpers:
    """Test ha_list_helpers MCP tool."""

    async def test_list_all_helpers(self, hass):
        """Test listing all helpers without filter."""
        result = await call_tool(
            hass,
            "ha_list_helpers",
            {},
            check_permission=lambda h, p: True
        )

        assert isinstance(result, list)
        for helper in result:
            assert "id" in helper
            assert "name" in helper
            assert "domain" in helper

    async def test_list_by_domain(self, hass):
        """Test listing helpers filtered by domain."""
        result = await call_tool(
            hass,
            "ha_list_helpers",
            {"domain": "input_boolean"},
            check_permission=lambda h, p: True
        )

        for helper in result:
            assert helper["domain"] == "input_boolean"

    async def test_permission_denied(self, hass):
        """Test that permission is checked."""
        with pytest.raises(PermissionError):
            await call_tool(
                hass,
                "ha_list_helpers",
                {},
                check_permission=lambda h, p: False
            )
```

### 3.2 ha_get_helper

**Test File:** `tests/mcp/test_mcp_get_helper.py`

| Test ID | Arguments | Expected Result |
|---------|-----------|-----------------|
| `test_get_by_full_id` | `{"helper_id": "input_boolean.test"}` | Helper details |
| `test_get_by_short_id` | `{"helper_id": "test"}` (with domain) | Helper details |
| `test_get_not_found` | `{"helper_id": "nonexistent"}` | `ValueError` |
| `test_get_includes_all_fields` | Valid ID | All domain-specific fields |

### 3.3 ha_create_helper

**Test File:** `tests/mcp/test_mcp_create_helper.py`

| Test ID | Domain | Arguments | Expected Result |
|---------|--------|-----------|-----------------|
| `test_create_input_boolean` | `input_boolean` | `{"domain": "input_boolean", "name": "Test"}` | Created helper |
| `test_create_input_number` | `input_number` | `{"domain": "input_number", "name": "Test", "min": 0, "max": 100}` | Created helper |
| `test_create_input_text` | `input_text` | `{"domain": "input_text", "name": "Test"}` | Created helper |
| `test_create_input_select` | `input_select` | `{"domain": "input_select", "name": "Test", "options": ["a", "b"]}` | Created helper |
| `test_create_input_datetime` | `input_datetime` | `{"domain": "input_datetime", "name": "Test", "has_date": true}` | Created helper |
| `test_create_counter` | `counter` | `{"domain": "counter", "name": "Test"}` | Created helper |
| `test_create_timer` | `timer` | `{"domain": "timer", "name": "Test", "duration": "00:05:00"}` | Created helper |
| `test_create_missing_name` | Any | `{"domain": "input_boolean"}` | `ValueError` |
| `test_create_missing_domain` | - | `{"name": "Test"}` | `ValueError` |

### 3.4 ha_update_helper

**Test File:** `tests/mcp/test_mcp_update_helper.py`

| Test ID | Arguments | Expected Result |
|---------|-----------|-----------------|
| `test_update_name` | `{"helper_id": "...", "name": "New Name"}` | Updated helper |
| `test_update_icon` | `{"helper_id": "...", "icon": "mdi:new-icon"}` | Updated helper |
| `test_update_domain_specific` | Domain-specific fields | Updated helper |
| `test_update_not_found` | `{"helper_id": "nonexistent"}` | `ValueError` |
| `test_partial_update` | Only subset of fields | Other fields unchanged |

### 3.5 ha_delete_helper

**Test File:** `tests/mcp/test_mcp_delete_helper.py`

| Test ID | Arguments | Expected Result |
|---------|-----------|-----------------|
| `test_delete_existing` | `{"helper_id": "input_boolean.test"}` | `{"deleted": "..."}` |
| `test_delete_not_found` | `{"helper_id": "nonexistent"}` | `ValueError` |
| `test_delete_removes_entity` | Valid ID | Entity no longer exists in HA |

---

## 4. REST API Tests

### 4.1 GET /api/config_mcp/helpers

**Test File:** `tests/api/test_api_helpers_list.py`

| Test ID | Query Params | Expected Status | Response |
|---------|--------------|-----------------|----------|
| `test_list_all` | None | 200 | Array of helpers |
| `test_list_by_domain` | `?domain=input_boolean` | 200 | Filtered array |
| `test_list_invalid_domain` | `?domain=invalid` | 400 | Error message |
| `test_list_no_auth` | None (no token) | 401 | Unauthorized |
| `test_list_permission_disabled` | None | 403 | Permission denied |

```python
@pytest.mark.api
class TestAPIListHelpers:
    """Test GET /api/config_mcp/helpers endpoint."""

    async def test_list_all(self, client, auth_header):
        """Test listing all helpers."""
        response = await client.get(
            "/api/config_mcp/helpers",
            headers=auth_header
        )

        assert response.status == 200
        data = await response.json()
        assert isinstance(data, list)

    async def test_list_by_domain(self, client, auth_header):
        """Test filtering by domain."""
        response = await client.get(
            "/api/config_mcp/helpers?domain=input_boolean",
            headers=auth_header
        )

        assert response.status == 200
        data = await response.json()
        for helper in data:
            assert helper["domain"] == "input_boolean"

    async def test_unauthorized(self, client):
        """Test request without auth token."""
        response = await client.get("/api/config_mcp/helpers")
        assert response.status == 401
```

### 4.2 GET /api/config_mcp/helpers/{helper_id}

| Test ID | Path | Expected Status | Response |
|---------|------|-----------------|----------|
| `test_get_existing` | `/helpers/input_boolean.test` | 200 | Helper details |
| `test_get_not_found` | `/helpers/nonexistent` | 404 | Not found error |
| `test_get_permission_disabled` | Valid path | 403 | Permission denied |

### 4.3 POST /api/config_mcp/helpers

| Test ID | Body | Expected Status | Response |
|---------|------|-----------------|----------|
| `test_create_valid` | Valid helper data | 201 | Created helper |
| `test_create_invalid_json` | Invalid JSON | 400 | Parse error |
| `test_create_missing_name` | Missing name | 400 | Validation error |
| `test_create_missing_domain` | Missing domain | 400 | Validation error |
| `test_create_duplicate` | Existing name | 409 | Conflict error |
| `test_create_non_admin` | Valid (non-admin user) | 401 | Admin required |
| `test_create_permission_disabled` | Valid | 403 | Permission denied |

```python
@pytest.mark.api
class TestAPICreateHelper:
    """Test POST /api/config_mcp/helpers endpoint."""

    async def test_create_input_boolean(self, client, admin_auth_header):
        """Test creating an input_boolean helper."""
        response = await client.post(
            "/api/config_mcp/helpers",
            json={
                "domain": "input_boolean",
                "name": "API Test Boolean",
                "icon": "mdi:toggle-switch"
            },
            headers=admin_auth_header
        )

        assert response.status == 201
        data = await response.json()
        assert "id" in data
        assert data["name"] == "API Test Boolean"

    async def test_create_non_admin(self, client, user_auth_header):
        """Test that non-admin users cannot create helpers."""
        response = await client.post(
            "/api/config_mcp/helpers",
            json={"domain": "input_boolean", "name": "Test"},
            headers=user_auth_header
        )

        assert response.status == 401
```

### 4.4 PATCH /api/config_mcp/helpers/{helper_id}

| Test ID | Path | Body | Expected Status | Response |
|---------|------|------|-----------------|----------|
| `test_update_name` | Valid ID | `{"name": "New"}` | 200 | Updated helper |
| `test_update_not_found` | Invalid ID | Valid body | 404 | Not found |
| `test_update_validation_error` | Valid ID | Invalid values | 400 | Validation error |
| `test_update_non_admin` | Valid ID | Valid body | 401 | Admin required |

### 4.5 DELETE /api/config_mcp/helpers/{helper_id}

| Test ID | Path | Expected Status | Response |
|---------|------|-----------------|----------|
| `test_delete_existing` | Valid ID | 204 | No content |
| `test_delete_not_found` | Invalid ID | 404 | Not found |
| `test_delete_non_admin` | Valid ID | 401 | Admin required |
| `test_delete_permission_disabled` | Valid ID | 403 | Permission denied |

---

## 5. Permission Tests

### 5.1 Permission Configuration

**Test File:** `tests/permissions/test_helpers_permissions.py`

| Test ID | Config | Operation | Expected |
|---------|--------|-----------|----------|
| `test_read_disabled_blocks_list` | `helpers_read: false` | List helpers | 403 Forbidden |
| `test_read_disabled_blocks_get` | `helpers_read: false` | Get helper | 403 Forbidden |
| `test_read_enabled_allows_list` | `helpers_read: true` | List helpers | 200 OK |
| `test_create_requires_admin` | `helpers_create: true` | Create (non-admin) | 401 Unauthorized |
| `test_create_admin_allowed` | `helpers_create: true` | Create (admin) | 201 Created |
| `test_update_requires_admin` | `helpers_update: true` | Update (non-admin) | 401 Unauthorized |
| `test_delete_requires_admin` | `helpers_delete: true` | Delete (non-admin) | 401 Unauthorized |
| `test_all_disabled` | All `false` | Any operation | 403 Forbidden |

### 5.2 Error Message Verification

| Test ID | Scenario | Expected Error Message |
|---------|----------|------------------------|
| `test_read_disabled_message` | Read disabled | "Helper read permission is disabled" |
| `test_create_disabled_message` | Create disabled | "Helper create permission is disabled" |
| `test_admin_required_message` | Non-admin user | "Admin permission required" |

```python
@pytest.mark.permissions
class TestHelperPermissions:
    """Test permission enforcement for helper operations."""

    @pytest.mark.parametrize("permission,operation,expected_status", [
        ("helpers_read", "list", 403),
        ("helpers_read", "get", 403),
        ("helpers_create", "create", 403),
        ("helpers_update", "update", 403),
        ("helpers_delete", "delete", 403),
    ])
    async def test_permission_disabled(
        self, hass, permission, operation, expected_status
    ):
        """Test that disabled permissions block operations."""
        # Disable the specific permission
        with patch_config({permission: False}):
            response = await perform_operation(hass, operation)
            assert response.status == expected_status

    async def test_admin_required_error_message(self, client, user_auth_header):
        """Test error message when admin is required."""
        response = await client.post(
            "/api/config_mcp/helpers",
            json={"domain": "input_boolean", "name": "Test"},
            headers=user_auth_header
        )

        assert response.status == 401
        data = await response.json()
        assert "admin" in data.get("message", "").lower()
```

---

## 6. Edge Cases

### 6.1 Invalid Domain Type

| Test ID | Input | Expected |
|---------|-------|----------|
| `test_domain_not_string` | `domain: 123` | Validation error |
| `test_domain_empty_string` | `domain: ""` | Validation error |
| `test_domain_unknown` | `domain: "input_invalid"` | "Invalid domain" error |
| `test_domain_case_sensitive` | `domain: "INPUT_BOOLEAN"` | Validation error |

### 6.2 Non-existent Helper ID

| Test ID | Operation | ID Format | Expected |
|---------|-----------|-----------|----------|
| `test_get_nonexistent` | GET | `input_boolean.does_not_exist` | 404 |
| `test_update_nonexistent` | PATCH | `nonexistent_id` | 404 |
| `test_delete_nonexistent` | DELETE | `nonexistent_id` | 404 |
| `test_get_wrong_domain_prefix` | GET | `wrong_domain.id` | 404 |

### 6.3 Duplicate Helper Name

| Test ID | Scenario | Expected |
|---------|----------|----------|
| `test_create_duplicate_name_same_domain` | Same name in same domain | 409 Conflict |
| `test_create_duplicate_name_different_domain` | Same name, different domain | Success (allowed) |
| `test_update_to_duplicate_name` | Update name to existing | 409 Conflict |

### 6.4 Invalid Field Values

**input_number specific:**

| Test ID | Fields | Expected Error |
|---------|--------|----------------|
| `test_min_greater_than_max` | `min: 100, max: 0` | "min must be less than max" |
| `test_step_zero` | `step: 0` | "step must be positive" |
| `test_step_negative` | `step: -1` | "step must be positive" |
| `test_initial_below_min` | `initial: -10, min: 0` | "initial must be >= min" |
| `test_initial_above_max` | `initial: 200, max: 100` | "initial must be <= max" |
| `test_mode_invalid` | `mode: "invalid"` | "mode must be slider or box" |

**input_text specific:**

| Test ID | Fields | Expected Error |
|---------|--------|----------------|
| `test_min_greater_than_max` | `min: 50, max: 10` | "min must be less than max" |
| `test_pattern_invalid_regex` | `pattern: "["` | "Invalid regex pattern" |
| `test_max_exceeds_limit` | `max: 500` | "max cannot exceed 255" |
| `test_mode_invalid` | `mode: "password"` | "mode must be text or password" |

**input_select specific:**

| Test ID | Fields | Expected Error |
|---------|--------|----------------|
| `test_options_empty` | `options: []` | "options cannot be empty" |
| `test_options_not_array` | `options: "string"` | "options must be an array" |
| `test_initial_not_in_options` | `initial: "x", options: ["a", "b"]` | "initial must be in options" |
| `test_options_duplicates` | `options: ["a", "a", "b"]` | "options must be unique" |

**input_datetime specific:**

| Test ID | Fields | Expected Error |
|---------|--------|----------------|
| `test_no_date_or_time` | `has_date: false, has_time: false` | "must have date or time" |

**counter specific:**

| Test ID | Fields | Expected Error |
|---------|--------|----------------|
| `test_minimum_greater_than_maximum` | `minimum: 100, maximum: 0` | "minimum must be <= maximum" |
| `test_initial_below_minimum` | `initial: -5, minimum: 0` | "initial must be >= minimum" |
| `test_step_zero` | `step: 0` | "step must be positive" |

**timer specific:**

| Test ID | Fields | Expected Error |
|---------|--------|----------------|
| `test_duration_invalid_format` | `duration: "invalid"` | "Invalid duration format" |
| `test_duration_negative` | `duration: "-00:05:00"` | "duration must be positive" |
| `test_duration_too_long` | `duration: "999:99:99"` | "duration exceeds maximum" |

### 6.5 Missing Required Fields

| Test ID | Domain | Missing Field | Expected |
|---------|--------|---------------|----------|
| `test_missing_name` | All | `name` | "Missing required field: name" |
| `test_missing_domain` | - | `domain` | "Missing required field: domain" |
| `test_input_number_missing_min` | `input_number` | `min` | "Missing required field: min" |
| `test_input_number_missing_max` | `input_number` | `max` | "Missing required field: max" |
| `test_input_select_missing_options` | `input_select` | `options` | "Missing required field: options" |

```python
@pytest.mark.edge_cases
class TestEdgeCases:
    """Test edge cases for helper operations."""

    async def test_input_number_min_greater_than_max(self, client, admin_auth_header):
        """Test that min > max is rejected."""
        response = await client.post(
            "/api/config_mcp/helpers",
            json={
                "domain": "input_number",
                "name": "Invalid Number",
                "min": 100,
                "max": 0
            },
            headers=admin_auth_header
        )

        assert response.status == 400
        data = await response.json()
        assert "min" in data.get("message", "").lower()
        assert "max" in data.get("message", "").lower()

    async def test_input_select_initial_not_in_options(
        self, client, admin_auth_header
    ):
        """Test that initial value must be in options."""
        response = await client.post(
            "/api/config_mcp/helpers",
            json={
                "domain": "input_select",
                "name": "Invalid Select",
                "options": ["a", "b", "c"],
                "initial": "x"
            },
            headers=admin_auth_header
        )

        assert response.status == 400
        data = await response.json()
        assert "initial" in data.get("message", "").lower()
```

---

## 7. Manual Testing Steps

### 7.1 Prerequisites

1. Home Assistant instance running with config_mcp integration installed
2. Admin user with long-lived access token
3. At least one helper of each type already created (for read tests)
4. curl or similar HTTP client
5. MCP client (Claude Code) configured with the server

### 7.2 REST API Manual Tests

#### Test 1: List All Helpers

```bash
# Expected: 200 OK with array of helpers
curl -X GET \
  -H "Authorization: Bearer YOUR_TOKEN" \
  https://your-ha:8123/api/config_mcp/helpers
```

**Expected Response:**
```json
[
  {
    "id": "test_boolean",
    "name": "Test Boolean",
    "domain": "input_boolean",
    "icon": "mdi:toggle-switch",
    "entity_id": "input_boolean.test_boolean"
  }
]
```

#### Test 2: List Helpers by Domain

```bash
# Expected: 200 OK with only input_number helpers
curl -X GET \
  -H "Authorization: Bearer YOUR_TOKEN" \
  "https://your-ha:8123/api/config_mcp/helpers?domain=input_number"
```

#### Test 3: Get Specific Helper

```bash
# Expected: 200 OK with helper details
curl -X GET \
  -H "Authorization: Bearer YOUR_TOKEN" \
  https://your-ha:8123/api/config_mcp/helpers/input_boolean.test_boolean
```

#### Test 4: Create Input Boolean

```bash
# Expected: 201 Created
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "input_boolean",
    "name": "Manual Test Boolean",
    "icon": "mdi:lightbulb"
  }' \
  https://your-ha:8123/api/config_mcp/helpers
```

#### Test 5: Create Input Number

```bash
# Expected: 201 Created
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "input_number",
    "name": "Manual Test Number",
    "min": 0,
    "max": 100,
    "step": 5,
    "mode": "slider",
    "unit_of_measurement": "%"
  }' \
  https://your-ha:8123/api/config_mcp/helpers
```

#### Test 6: Create Input Select

```bash
# Expected: 201 Created
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "input_select",
    "name": "Manual Test Select",
    "options": ["Option A", "Option B", "Option C"],
    "icon": "mdi:format-list-bulleted"
  }' \
  https://your-ha:8123/api/config_mcp/helpers
```

#### Test 7: Update Helper

```bash
# Expected: 200 OK with updated helper
curl -X PATCH \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Updated Name",
    "icon": "mdi:star"
  }' \
  https://your-ha:8123/api/config_mcp/helpers/input_boolean.manual_test_boolean
```

#### Test 8: Delete Helper

```bash
# Expected: 204 No Content
curl -X DELETE \
  -H "Authorization: Bearer YOUR_TOKEN" \
  https://your-ha:8123/api/config_mcp/helpers/input_boolean.manual_test_boolean
```

### 7.3 MCP Tool Manual Tests

Using Claude Code with the config-mcp server configured:

#### Test 1: List Helpers

```
User: List all helpers in Home Assistant

Expected Claude Response:
- Should call ha_list_helpers tool
- Should display helpers grouped by domain
- Should show name, id, and relevant properties
```

#### Test 2: Create Input Boolean via MCP

```
User: Create a new input_boolean helper called "Test MCP Boolean" with a lightbulb icon

Expected Claude Response:
- Should call ha_create_helper with:
  - domain: "input_boolean"
  - name: "Test MCP Boolean"
  - icon: "mdi:lightbulb"
- Should confirm creation with helper ID
```

#### Test 3: Create Input Number via MCP

```
User: Create an input_number helper called "Temperature Setpoint" with min 15, max 30, step 0.5

Expected Claude Response:
- Should call ha_create_helper with:
  - domain: "input_number"
  - name: "Temperature Setpoint"
  - min: 15
  - max: 30
  - step: 0.5
```

#### Test 4: Get Helper Details

```
User: Show me details about the input_boolean.test_mcp_boolean helper

Expected Claude Response:
- Should call ha_get_helper
- Should display all helper properties
```

#### Test 5: Update Helper

```
User: Change the name of input_boolean.test_mcp_boolean to "Updated MCP Boolean"

Expected Claude Response:
- Should call ha_update_helper with new name
- Should confirm the update
```

#### Test 6: Delete Helper

```
User: Delete the input_boolean.test_mcp_boolean helper

Expected Claude Response:
- Should call ha_delete_helper
- Should confirm deletion
```

### 7.4 Home Assistant UI Verification

After each create/update/delete operation, verify in the HA UI:

1. **Settings > Devices & Services > Helpers**
   - Created helpers appear in the list
   - Helper properties match what was set via API
   - Deleted helpers are removed from the list

2. **Developer Tools > States**
   - Created helper entities appear with correct entity_id
   - Entity attributes match configured values
   - Deleted entities no longer appear

3. **Developer Tools > Services**
   - Helper-specific services work (e.g., `input_boolean.turn_on`)
   - Counter increment/decrement work
   - Timer start/pause/cancel work

### 7.5 Error Case Manual Tests

#### Test: Permission Denied

```bash
# With helpers_read disabled in config
curl -X GET \
  -H "Authorization: Bearer YOUR_TOKEN" \
  https://your-ha:8123/api/config_mcp/helpers

# Expected: 403 Forbidden with message about permission
```

#### Test: Non-Admin Create

```bash
# Using a non-admin user's token
curl -X POST \
  -H "Authorization: Bearer NON_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"domain": "input_boolean", "name": "Should Fail"}' \
  https://your-ha:8123/api/config_mcp/helpers

# Expected: 401 Unauthorized
```

#### Test: Invalid Domain

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"domain": "invalid_domain", "name": "Test"}' \
  https://your-ha:8123/api/config_mcp/helpers

# Expected: 400 Bad Request with message about invalid domain
```

#### Test: Min Greater Than Max

```bash
curl -X POST \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "input_number",
    "name": "Invalid",
    "min": 100,
    "max": 0
  }' \
  https://your-ha:8123/api/config_mcp/helpers

# Expected: 400 Bad Request with validation error
```

---

## 8. Test Coverage Requirements

### 8.1 Coverage Targets

| Category | Target |
|----------|--------|
| Statement Coverage | >= 80% |
| Branch Coverage | >= 75% |
| Function Coverage | >= 80% |
| Line Coverage | >= 80% |

### 8.2 Critical Paths (100% Coverage Required)

- Permission checking logic
- Input validation for each domain
- WebSocket API calls
- Error response generation
- Entity ID generation

### 8.3 Test Execution Commands

```bash
# Run all helper tests
pytest tests/ -k helper -v

# Run with coverage
pytest tests/ -k helper --cov=custom_components.config_mcp.tools.helpers \
  --cov=custom_components.config_mcp.views.helpers \
  --cov-report=html

# Run specific test categories
pytest tests/unit/ -k helper -v          # Unit tests only
pytest tests/integration/ -k helper -v   # Integration tests only
pytest tests/mcp/ -k helper -v           # MCP tool tests only
pytest tests/api/ -k helper -v           # REST API tests only
pytest tests/permissions/ -k helper -v   # Permission tests only
pytest tests/edge_cases/ -k helper -v    # Edge case tests only
```

---

## 9. Test Data

### 9.1 Test Fixtures

```python
# conftest.py

@pytest.fixture
def input_boolean_data():
    """Valid input_boolean helper data."""
    return {
        "domain": "input_boolean",
        "name": "Test Boolean",
        "icon": "mdi:toggle-switch",
        "initial": True
    }

@pytest.fixture
def input_number_data():
    """Valid input_number helper data."""
    return {
        "domain": "input_number",
        "name": "Test Number",
        "min": 0,
        "max": 100,
        "step": 1,
        "mode": "slider",
        "unit_of_measurement": "%",
        "initial": 50
    }

@pytest.fixture
def input_text_data():
    """Valid input_text helper data."""
    return {
        "domain": "input_text",
        "name": "Test Text",
        "min": 0,
        "max": 100,
        "mode": "text",
        "pattern": "[a-zA-Z0-9]+"
    }

@pytest.fixture
def input_select_data():
    """Valid input_select helper data."""
    return {
        "domain": "input_select",
        "name": "Test Select",
        "options": ["Option A", "Option B", "Option C"],
        "icon": "mdi:format-list-bulleted",
        "initial": "Option A"
    }

@pytest.fixture
def input_datetime_data():
    """Valid input_datetime helper data."""
    return {
        "domain": "input_datetime",
        "name": "Test DateTime",
        "has_date": True,
        "has_time": True,
        "icon": "mdi:calendar-clock"
    }

@pytest.fixture
def counter_data():
    """Valid counter helper data."""
    return {
        "domain": "counter",
        "name": "Test Counter",
        "initial": 0,
        "step": 1,
        "minimum": 0,
        "maximum": 100,
        "icon": "mdi:counter"
    }

@pytest.fixture
def timer_data():
    """Valid timer helper data."""
    return {
        "domain": "timer",
        "name": "Test Timer",
        "duration": "00:05:00",
        "icon": "mdi:timer",
        "restore": True
    }

@pytest.fixture
def all_helper_data(
    input_boolean_data,
    input_number_data,
    input_text_data,
    input_select_data,
    input_datetime_data,
    counter_data,
    timer_data
):
    """All valid helper data fixtures."""
    return {
        "input_boolean": input_boolean_data,
        "input_number": input_number_data,
        "input_text": input_text_data,
        "input_select": input_select_data,
        "input_datetime": input_datetime_data,
        "counter": counter_data,
        "timer": timer_data,
    }
```

---

## 10. Appendix

### A. WebSocket API Reference

```python
# List helpers
await hass.connection.send_message({
    "type": "input_boolean/list"
})
# Response: {"success": true, "result": [...]}

# Create helper
await hass.connection.send_message({
    "type": "input_boolean/create",
    "name": "Test",
    "icon": "mdi:toggle-switch"
})
# Response: {"success": true, "result": {"id": "...", ...}}

# Update helper
await hass.connection.send_message({
    "type": "input_boolean/update",
    "input_boolean_id": "test",
    "name": "Updated"
})
# Response: {"success": true, "result": {...}}

# Delete helper
await hass.connection.send_message({
    "type": "input_boolean/delete",
    "input_boolean_id": "test"
})
# Response: {"success": true}
```

### B. Domain-Specific Required Fields

| Domain | Required Create Fields | Required Update Fields |
|--------|------------------------|------------------------|
| `input_boolean` | `name` | `input_boolean_id` |
| `input_number` | `name`, `min`, `max` | `input_number_id` |
| `input_text` | `name` | `input_text_id` |
| `input_select` | `name`, `options` | `input_select_id` |
| `input_datetime` | `name`, (`has_date` or `has_time`) | `input_datetime_id` |
| `counter` | `name` | `counter_id` |
| `timer` | `name` | `timer_id` |

### C. HTTP Status Code Reference

| Status | Usage |
|--------|-------|
| 200 OK | Successful GET, PATCH |
| 201 Created | Successful POST |
| 204 No Content | Successful DELETE |
| 400 Bad Request | Validation error, invalid JSON |
| 401 Unauthorized | Missing token, non-admin user |
| 403 Forbidden | Permission disabled |
| 404 Not Found | Helper not found |
| 409 Conflict | Duplicate name |
| 500 Internal Server Error | Unexpected error |
