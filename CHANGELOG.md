# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.3.0] - 2025-03-08

### Added
- Helper support for 7 types: input_boolean, input_number, input_text, input_select, input_datetime, counter, timer
- HACS brand images (icon + logo) in `brand/` directory for HA 2026.3+ local brand display
- GitHub Actions CI for HACS validation and hassfest validation
- `issue_tracker` and `loggers` fields in manifest.json
- `hide_default_branch` in hacs.json to enforce tagged release installs

### Fixed
- Helpers now use Store API instead of `hass.data` for reliable state access
- MCP connection stability in Streamable HTTP transport

## [1.2.1] - 2025-02-15

### Fixed
- `ha_get_automation` handles numeric IDs from UI-created automations (#2)

## [1.2.0] - 2025-02-01

### Added
- Category and label management tools and views

## [1.1.0] - 2025-01-15

### Added
- Entity validation for all tool inputs
- Log reading capabilities

### Fixed
- Performance improvements across MCP tools
- FloorRegistry method name in `list_floors` tool

## [1.0.0] - 2025-01-01

### Added
- Full MCP (Model Context Protocol) server implementation
- Streamable HTTP and SSE transport support
- OAuth / JWT authentication
- Dashboard CRUD operations (create, read, update, delete)
- Automation management tools
- Script management tools
- Scene management tools
- Device and entity discovery APIs
- Integration listing and details
- Area management
- Granular permission configuration via config flow
- REST API endpoints for all resources at `/api/config_mcp/`

## [0.2.0] - 2024-12-15

### Added
- Discovery APIs for devices, entities, integrations, and areas
- Granular config flow with per-resource enable/disable

## [0.1.0] - 2024-12-01

### Added
- Initial release
- HACS configuration
- Config flow UI with resource selection
- Dashboard CRUD operations with PATCH support

[1.3.0]: https://github.com/keith-gamble/hass-configuration-mcp/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/keith-gamble/hass-configuration-mcp/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/keith-gamble/hass-configuration-mcp/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/keith-gamble/hass-configuration-mcp/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/keith-gamble/hass-configuration-mcp/compare/v0.2.0...v1.0.0
[0.2.0]: https://github.com/keith-gamble/hass-configuration-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/keith-gamble/hass-configuration-mcp/releases/tag/v0.1.0
