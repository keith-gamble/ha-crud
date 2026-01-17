# Configuration MCP Server

A Home Assistant custom component that exposes an MCP (Model Context Protocol) server and REST API endpoints for managing Home Assistant configuration programmatically. Designed for integration with AI assistants like Claude Code.

## Features

- **MCP Server** - Native MCP protocol support for AI assistants
- **Lovelace Dashboards** - Full CRUD operations for dashboards and views
- **Automations** - Create, update, delete, enable/disable, and trigger automations
- **Scripts** - Create, update, delete, run, and stop scripts
- **Scenes** - Create, update, delete, and activate scenes
- **Helpers** - Create, update, delete input helpers (input_boolean, input_number, input_text, input_select, input_datetime, counter, timer)
- **System Discovery** - Query entities, devices, areas, floors, integrations, and services
- **Categories & Labels** - Manage categories and labels for organizing automations/scripts
- **Log Reading** - Access Home Assistant logs for debugging
- **OAuth Support** - Browser-based authentication for MCP clients (requires hass-oidc-auth)
- **Granular Permissions** - Enable/disable each capability independently

## Installation

### HACS (Recommended)

1. Add this repository as a custom repository in HACS
2. Search for "Configuration MCP Server" and install
3. Restart Home Assistant
4. Go to Settings > Integrations > Add Integration > "Configuration MCP Server"
5. Configure which capabilities to enable

### Manual Installation

1. Copy the `custom_components/config_mcp` folder to your Home Assistant config directory
2. Restart Home Assistant
3. Go to Settings > Integrations > Add Integration > "Configuration MCP Server"

## MCP Server Setup

### Claude Code - Token Authentication (Recommended)

```bash
claude mcp add --transport http config-mcp \
  https://your-ha-instance:8123/api/config_mcp/mcp \
  --header "Authorization: Bearer YOUR_LONG_LIVED_TOKEN"
```

### Claude Code - OAuth Authentication

If OAuth is enabled (requires hass-oidc-auth):

```bash
claude mcp add --transport http config-mcp \
  https://your-ha-instance:8123/api/config_mcp/mcp
```

Then run `/mcp` in Claude Code and select "Authenticate" to login via browser.

## Available MCP Tools

### Dashboards
| Tool | Description |
|------|-------------|
| `ha_list_dashboards` | List all Lovelace dashboards |
| `ha_get_dashboard` | Get dashboard metadata |
| `ha_get_dashboard_config` | Get dashboard views/cards |
| `ha_create_dashboard` | Create new dashboard |
| `ha_update_dashboard` | Update dashboard metadata |
| `ha_update_dashboard_config` | Replace dashboard config |
| `ha_delete_dashboard` | Delete dashboard |

### Automations
| Tool | Description |
|------|-------------|
| `ha_list_automations` | List all automations |
| `ha_get_automation` | Get automation details |
| `ha_create_automation` | Create new automation |
| `ha_update_automation` | Update automation |
| `ha_delete_automation` | Delete automation |
| `ha_trigger_automation` | Manually trigger automation |

### Scripts
| Tool | Description |
|------|-------------|
| `ha_list_scripts` | List all scripts |
| `ha_get_script` | Get script details |
| `ha_create_script` | Create new script |
| `ha_update_script` | Update script |
| `ha_delete_script` | Delete script |
| `ha_run_script` | Run a script |
| `ha_stop_script` | Stop a running script |

### Scenes
| Tool | Description |
|------|-------------|
| `ha_list_scenes` | List all scenes |
| `ha_get_scene` | Get scene details |
| `ha_create_scene` | Create new scene |
| `ha_update_scene` | Update scene |
| `ha_delete_scene` | Delete scene |
| `ha_activate_scene` | Activate a scene |

### Helpers
| Tool | Description |
|------|-------------|
| `ha_list_helpers` | List all helpers with optional domain filter |
| `ha_get_helper` | Get helper details by entity_id |
| `ha_create_helper` | Create new helper (input_boolean, input_number, etc.) |
| `ha_update_helper` | Update helper configuration |
| `ha_delete_helper` | Delete helper |

**Supported helper domains:**
- `input_boolean` - Toggle switches
- `input_number` - Numeric inputs with min/max/step
- `input_text` - Text inputs with pattern validation
- `input_select` - Dropdown selections
- `input_datetime` - Date and/or time inputs
- `counter` - Increment/decrement counters
- `timer` - Duration timers

### System Discovery
| Tool | Description |
|------|-------------|
| `ha_list_entities` | List entities with filtering |
| `ha_get_entity` | Get entity details |
| `ha_list_domains` | List entity domains |
| `ha_list_devices` | List devices with filtering |
| `ha_get_device` | Get device details |
| `ha_list_areas` | List all areas |
| `ha_get_area` | Get area details |
| `ha_list_floors` | List all floors |
| `ha_list_integrations` | List active integrations |
| `ha_list_services` | List available services |
| `ha_get_service` | Get service details |

### Categories & Labels
| Tool | Description |
|------|-------------|
| `ha_list_categories` | List categories by scope (automation/script/helper) |
| `ha_get_category` | Get category details |
| `ha_create_category` | Create new category |
| `ha_update_category` | Update category name/icon |
| `ha_delete_category` | Delete category |
| `ha_list_labels` | List all labels |
| `ha_get_label` | Get label details |
| `ha_create_label` | Create new label |
| `ha_update_label` | Update label properties |
| `ha_delete_label` | Delete label |

> **Note:** Use `ha_patch_automation` or `ha_patch_script` with `category_id` and `labels` parameters to assign categories/labels to automations and scripts.

### Logs
| Tool | Description |
|------|-------------|
| `ha_get_logs` | Get recent log entries |
| `ha_get_error_logs` | Get error/warning logs |

## REST API

All endpoints are available at `/api/config_mcp/`:

| Resource | Endpoint |
|----------|----------|
| MCP Server | `/api/config_mcp/mcp` |
| Dashboards | `/api/config_mcp/dashboards` |
| Automations | `/api/config_mcp/automations` |
| Scripts | `/api/config_mcp/scripts` |
| Scenes | `/api/config_mcp/scenes` |
| Helpers | `/api/config_mcp/helpers` |
| Entities | `/api/config_mcp/entities` |
| Devices | `/api/config_mcp/devices` |
| Areas | `/api/config_mcp/areas` |
| Floors | `/api/config_mcp/floors` |
| Integrations | `/api/config_mcp/integrations` |
| Services | `/api/config_mcp/services` |
| Categories | `/api/config_mcp/categories/{scope}` |
| Labels | `/api/config_mcp/labels` |
| Logs | `/api/config_mcp/logs` |

## Authentication

All endpoints require a valid Home Assistant long-lived access token:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" \
  https://your-ha-instance:8123/api/config_mcp/dashboards
```

## Configuration

After installation, configure via Settings > Integrations > Configuration MCP Server > Configure:

1. **MCP Server** - Enable/disable MCP server, OAuth, and log reading
2. **System Discovery** - Enable/disable entity, device, area, integration, and service discovery
3. **Lovelace Dashboards** - Granular read/create/update/delete permissions
4. **Automations** - Granular read/create/update/delete permissions
5. **Scripts** - Granular read/create/update/delete permissions
6. **Scenes** - Granular read/create/update/delete permissions
7. **Helpers** - Granular read/create/update/delete permissions for input helpers
8. **Categories & Labels** - Manage organizational categories and labels

## License

MIT License

## Contributing

Issues and pull requests welcome at the project repository.
