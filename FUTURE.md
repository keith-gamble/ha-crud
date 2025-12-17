# Future Resource Support - Functional Requirements Specification

This document outlines the planned CRUD API support for additional Home Assistant resources beyond dashboards.

## Overview

### Current Status (v0.2.0)

**Completed - Discovery APIs (Read-Only)**
- ✅ Entities - List/search all entities with states and attributes
- ✅ Devices - List devices with their associated entities
- ✅ Areas & Floors - Spatial organization hierarchy
- ✅ Integrations - Active integrations and config entries
- ✅ Services - Available services and their parameters
- ✅ Dashboards - Full CRUD operations

**Planned - Management APIs (CRUD)**
- ⬜ Automations - Create, update, delete, trigger
- ⬜ Scripts - Create, update, delete, run
- ⬜ Scenes - Create, update, delete, activate, snapshot
- ⬜ Blueprints - Import, instantiate, delete

### Problem Statement
Home Assistant provides no official REST API for these resources. The only interfaces are:
- **WebSocket API** - Used by the HA frontend, requires persistent connection
- **Service calls** - Can trigger/activate but not manage (create/update/delete)

This gap makes it difficult to integrate with automation tooling, CI/CD pipelines, and AI assistants via MCP.

### Design Goals
1. Consistent REST API following the same patterns as dashboard endpoints
2. Full CRUD operations where applicable
3. Action endpoints for triggering/activating resources
4. Bearer token authentication (long-lived access tokens)
5. Admin permission enforcement for write operations
6. Read-only support for YAML-defined resources

---

## 1. Automations API

### Storage
- **File**: `.storage/core.config_entries` (via `homeassistant.helpers.collection.StorageCollection`)
- **Internal**: `hass.data["automation"]` with entity registry

### Endpoints

| Method | Endpoint | Description | Admin Required |
|--------|----------|-------------|----------------|
| GET | `/api/ha_crud/automations` | List all automations | No |
| POST | `/api/ha_crud/automations` | Create new automation | Yes |
| GET | `/api/ha_crud/automations/{id}` | Get automation details | No |
| PUT | `/api/ha_crud/automations/{id}` | Full update | Yes |
| PATCH | `/api/ha_crud/automations/{id}` | Partial update | Yes |
| DELETE | `/api/ha_crud/automations/{id}` | Delete automation | Yes |
| POST | `/api/ha_crud/automations/{id}/trigger` | Trigger automation | Yes |
| POST | `/api/ha_crud/automations/{id}/enable` | Enable automation | Yes |
| POST | `/api/ha_crud/automations/{id}/disable` | Disable automation | Yes |

### Data Structure

#### List Response
```json
[
  {
    "id": "1234567890abcdef",
    "alias": "Turn on lights at sunset",
    "description": "Automatically turn on living room lights",
    "mode": "single",
    "state": "on",
    "last_triggered": "2024-01-15T18:30:00Z",
    "source": "storage"
  }
]
```

#### Full Automation Object
```json
{
  "id": "1234567890abcdef",
  "alias": "Turn on lights at sunset",
  "description": "Automatically turn on living room lights when the sun sets",
  "mode": "single",
  "trigger": [
    {
      "platform": "sun",
      "event": "sunset",
      "offset": "-00:30:00"
    }
  ],
  "condition": [
    {
      "condition": "state",
      "entity_id": "binary_sensor.someone_home",
      "state": "on"
    }
  ],
  "action": [
    {
      "service": "light.turn_on",
      "target": {
        "entity_id": "light.living_room"
      },
      "data": {
        "brightness_pct": 80
      }
    }
  ]
}
```

#### Create Request
```json
{
  "alias": "Turn on lights at sunset",
  "description": "Optional description",
  "mode": "single",
  "trigger": [...],
  "condition": [...],
  "action": [...]
}
```

**Required fields**: `alias`, `trigger`, `action`
**Optional fields**: `description`, `mode` (defaults to "single"), `condition`

### Mode Options
- `single` - Do not start a new run if already running
- `restart` - Cancel current run and start new
- `queued` - Queue additional runs (with optional `max` parameter)
- `parallel` - Run in parallel (with optional `max` parameter)

### Constraints
- YAML-defined automations return `source: "yaml"` and are read-only
- ID is auto-generated on create (UUID format)
- Deleting an automation also removes its entity from entity registry

---

## 2. Scripts API

### Endpoints

| Method | Endpoint | Description | Admin Required |
|--------|----------|-------------|----------------|
| GET | `/api/ha_crud/scripts` | List all scripts | No |
| POST | `/api/ha_crud/scripts` | Create new script | Yes |
| GET | `/api/ha_crud/scripts/{id}` | Get script details | No |
| PUT | `/api/ha_crud/scripts/{id}` | Full update | Yes |
| PATCH | `/api/ha_crud/scripts/{id}` | Partial update | Yes |
| DELETE | `/api/ha_crud/scripts/{id}` | Delete script | Yes |
| POST | `/api/ha_crud/scripts/{id}/run` | Execute script | Yes |

### Data Structure

#### Full Script Object
```json
{
  "id": "morning_routine",
  "alias": "Morning Routine",
  "description": "Run morning automation sequence",
  "mode": "single",
  "icon": "mdi:weather-sunny",
  "fields": {
    "brightness": {
      "description": "Light brightness level",
      "example": 80,
      "selector": {
        "number": {
          "min": 0,
          "max": 100
        }
      }
    }
  },
  "sequence": [...]
}
```

### Constraints
- Script IDs: lowercase letters, numbers, and underscores only (no hyphens)
- If `id` not provided, generated from alias (lowercase, spaces to underscores)
- YAML-defined scripts are read-only
- Scripts can define input `fields` for parameterized execution

---

## 3. Scenes API

### Endpoints

| Method | Endpoint | Description | Admin Required |
|--------|----------|-------------|----------------|
| GET | `/api/ha_crud/scenes` | List all scenes | No |
| POST | `/api/ha_crud/scenes` | Create new scene | Yes |
| GET | `/api/ha_crud/scenes/{id}` | Get scene details | No |
| PUT | `/api/ha_crud/scenes/{id}` | Full update | Yes |
| DELETE | `/api/ha_crud/scenes/{id}` | Delete scene | Yes |
| POST | `/api/ha_crud/scenes/{id}/activate` | Activate scene | Yes |
| POST | `/api/ha_crud/scenes/snapshot` | Create scene from current state | Yes |

### Data Structure

#### Full Scene Object
```json
{
  "id": "movie_time",
  "name": "Movie Time",
  "icon": "mdi:movie",
  "entities": {
    "light.living_room": {
      "state": "on",
      "brightness": 50,
      "color_temp": 400
    },
    "light.kitchen": {
      "state": "off"
    }
  }
}
```

### Snapshot Endpoint
Create a scene by capturing current entity states:

```bash
POST /api/ha_crud/scenes/snapshot
Content-Type: application/json

{
  "name": "Current Living Room",
  "entity_ids": [
    "light.living_room",
    "light.kitchen",
    "media_player.tv"
  ]
}
```

---

## 4. Blueprints API

### Endpoints

| Method | Endpoint | Description | Admin Required |
|--------|----------|-------------|----------------|
| GET | `/api/ha_crud/blueprints` | List all blueprints | No |
| GET | `/api/ha_crud/blueprints/{domain}` | List blueprints by domain | No |
| GET | `/api/ha_crud/blueprints/{domain}/{path}` | Get blueprint details | No |
| POST | `/api/ha_crud/blueprints/import` | Import blueprint from URL | Yes |
| DELETE | `/api/ha_crud/blueprints/{domain}/{path}` | Delete blueprint | Yes |
| POST | `/api/ha_crud/blueprints/{domain}/{path}/instantiate` | Create automation/script from blueprint | Yes |

### Import Request
```json
{
  "url": "https://github.com/home-assistant/core/blob/dev/homeassistant/components/automation/blueprints/motion_light.yaml"
}
```

### Instantiate Request
```json
{
  "name": "Kitchen Motion Light",
  "input": {
    "motion_entity": "binary_sensor.kitchen_motion",
    "light_target": {
      "entity_id": "light.kitchen"
    },
    "no_motion_wait": 300
  }
}
```

---

## Implementation Plan

### Priority Order
1. ✅ **Discovery APIs** - Entities, Devices, Areas, Integrations, Services (COMPLETED in v0.2.0)
2. ⬜ **Automations** - Most commonly managed, highest value for AI integration
3. ⬜ **Scripts** - Similar implementation pattern, complements automations
4. ⬜ **Scenes** - Simpler structure, useful for environment control
5. ⬜ **Blueprints** - Most complex, builds on automation implementation

### Files to Create (for remaining work)

```
custom_components/ha_crud/
├── views/
│   ├── automations.py       # New - Automation CRUD
│   ├── scripts.py           # New - Script CRUD (rename from services.py)
│   ├── scenes.py            # New - Scene CRUD
│   └── blueprints.py        # New - Blueprint CRUD
├── schemas/
│   ├── __init__.py          # New
│   ├── automations.py       # Validation schemas
│   ├── scripts.py           # Validation schemas
│   ├── scenes.py            # Validation schemas
│   └── blueprints.py        # Validation schemas
```

### MCP Tools to Add

#### Automation Tools
| Tool Name | Description |
|-----------|-------------|
| `ha_list_automations` | List all automations |
| `ha_get_automation` | Get automation details |
| `ha_create_automation` | Create new automation |
| `ha_update_automation` | Update automation |
| `ha_delete_automation` | Delete automation |
| `ha_trigger_automation` | Trigger an automation |

#### Script Tools
| Tool Name | Description |
|-----------|-------------|
| `ha_list_scripts` | List all scripts |
| `ha_get_script` | Get script details |
| `ha_create_script` | Create new script |
| `ha_update_script` | Update script |
| `ha_delete_script` | Delete script |
| `ha_run_script` | Execute a script |

#### Scene Tools
| Tool Name | Description |
|-----------|-------------|
| `ha_list_scenes` | List all scenes |
| `ha_get_scene` | Get scene details |
| `ha_create_scene` | Create new scene |
| `ha_update_scene` | Update scene |
| `ha_delete_scene` | Delete scene |
| `ha_activate_scene` | Activate a scene |
| `ha_snapshot_scene` | Create scene from current state |

#### Blueprint Tools
| Tool Name | Description |
|-----------|-------------|
| `ha_list_blueprints` | List all blueprints |
| `ha_get_blueprint` | Get blueprint details |
| `ha_import_blueprint` | Import blueprint from URL |
| `ha_delete_blueprint` | Delete blueprint |
| `ha_instantiate_blueprint` | Create automation/script from blueprint |

---

## Open Questions

1. **Automation/Script versioning**: Should we support version history or rollback?
2. **Bulk operations**: Should we support bulk create/update/delete?
3. **Webhooks**: Should we emit events when resources are modified via API?
4. **Rate limiting**: Should we implement rate limiting for write operations?
5. **Audit logging**: Should we log all API operations for security?
