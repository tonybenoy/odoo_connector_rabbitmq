# Odoo Connector RabbitMQ

Production-grade event-driven architecture for Odoo via RabbitMQ.

## Supported Versions

| Odoo Version | Branch | Status |
|-------------|--------|--------|
| 19.0 | [`19.0`](../../tree/19.0) / `main` | Supported |
| 18.0 | [`18.0`](../../tree/18.0) | Supported |
| 17.0 | [`17.0`](../../tree/17.0) | Supported |

## Features

- **Zero-code publishing** — configure Event Rules in the UI, no Python inheritance needed
- **Zero-code consuming** — field mapping mode creates/updates/deletes records from JSON messages
- **Transactional outbox pattern** for reliable message delivery
- **Automatic event capture** on create, write, unlink, and state changes
- **`@rabbitmq_event` decorator** for method-level event emission
- **Batch consumption** with configurable prefetch and manual acknowledgment
- **Retry with exponential backoff** and dead-letter handling
- **SSL/TLS** and cluster URI support
- **Connection pooling** with heartbeats and auto-reconnect
- **Multi-worker safe** using `SELECT FOR UPDATE SKIP LOCKED`
- **Monitoring UI** with event log viewer, filters, and grouping
- **Role-based access** (User / Manager groups)
- **Consumer safety** — delete action disabled by default, validated constraints on all rules
- **Backward compatible** — existing mixin-based and method-based integrations keep working

## Quick Start

### 1. Start RabbitMQ

```bash
docker compose -f odoo_connector_rabbitmq/docker-compose.yml up -d
```

### 2. Install the module

```bash
pip install pika>=1.3.0
```

Copy `odoo_connector_rabbitmq/` into your Odoo addons path and install **Odoo Connector RabbitMQ** from the Apps menu.

### 3. Configure

Go to **Settings > RabbitMQ** to set the connection and enable publishing/consuming.

## Usage

### Zero-code publishing (recommended)

No Python code needed. Just create an **Event Rule** in the UI:

1. Go to **RabbitMQ > Event Rules > Create**
2. Select the **Model** (e.g. `res.partner`)
3. Choose the **Event Type**: `create`, `write`, `unlink`, or `state_change`
4. Set the **Exchange** and **Routing Key** (supports `{model}` and `{event}` placeholders)
5. Optionally select **Tracked Fields** to only fire on specific field changes

That's it. Every matching ORM operation now emits an event to RabbitMQ automatically.

### Zero-code consuming with field mapping (recommended)

Process inbound messages without writing any Python:

1. Go to **RabbitMQ > Consumer Rules > Create**
2. Set the **Queue**, **Exchange**, and **Binding Key**
3. Set **Target Model** (e.g. `res.partner`)
4. Choose **Processing Mode**: `Field Mapping`
5. Select an **Action**: `Create`, `Update`, `Create or Update`, or `Delete`
6. For update/upsert/delete, set the **Match Field** (e.g. `email`)
7. Optionally set **Payload Root** for nested JSON (e.g. `data.partner`)
8. Add **Field Mappings** in the table:

| Source Field | Target Field | Type | Notes |
|-------------|-------------|------|-------|
| `first_name` | `name` | Text | |
| `email` | `email` | Text | |
| `country_code` | `country_id` | Many2One (by Search) | Search model: `res.country`, Search field: `code` |
| `is_active` | `active` | Boolean | |

Supported field types: Text, Integer, Float, Boolean, Date, Datetime, Many2One (by ID), Many2One (by Search), Raw.

Dot notation is supported for nested JSON keys (e.g. `address.city`).

> **Note:** The Delete action is disabled by default for safety. Enable it in **Settings > RabbitMQ > Consumer Safety**.

### Legacy: Publishing via mixin

For models that already inherit the mixin, this still works:

```python
from odoo import models

class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'rabbitmq.event.bus.mixin']
```

Models using the mixin are automatically skipped by the global hook to prevent double-firing.

### Decorator

Use `@rabbitmq_event` on any method to emit an event after execution:

```python
from odoo.addons.odoo_connector_rabbitmq.decorator import rabbitmq_event

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @rabbitmq_event('order_confirmed', exchange='sales', routing_key='order.confirmed')
    def action_confirm(self):
        return super().action_confirm()
```

### Legacy: Consuming via method call

Create a **Consumer Rule** with processing mode `Call Method`:

```python
import json
from odoo import models

class MyConsumer(models.Model):
    _name = 'my.consumer'

    def process_message(self, body, properties):
        data = json.loads(body)
        # handle the message
```

Configure the Consumer Rule with:
- **Processing Mode**: `Call Method`
- **Target Model**: `my.consumer`
- **Target Method**: `process_message`

## Architecture

```
Odoo Model ──► Global Hook / Event Rule
                    │
                    ▼
             Event Log (outbox)
                    │
              ┌─────┴─────┐
              │  Cron Job  │  (1-min cycle)
              └─────┬─────┘
                    │
                    ▼
              RabbitMQ Broker
                    │
              ┌─────┴─────┐
              │  Cron Job  │  (2-min cycle)
              └─────┬─────┘
                    │
                    ▼
           Consumer Rule ──► Field Mapping / Target Method
```

### How the global hook works

At module load time (`post_load`), `BaseModel.create`, `write`, and `unlink` are patched once. Every ORM operation hits an inlined fast path:

```
cache = registry._rabbitmq_rules_cache   # 1 direct attr access
self._name in cache                       # 1 dict 'in' check → False
```

For models with no rules, the overhead is **1 attribute access + 1 dict lookup** (~nanoseconds). All filtering (skip internal models, transients, mixin models) is done once at cache build time, not per-call.

The cache is invalidated automatically when:
- Event Rules are created, modified, or deleted
- Settings are changed in **Settings > RabbitMQ**

New rules take effect immediately — no restart needed.

All event logic runs inside `try/except` — event bus bugs never break normal ORM operations.

The global hook can be disabled entirely in **Settings > RabbitMQ > Enable Global Hook**.

### Key design patterns

- **Transactional outbox**: Events are logged atomically with business operations, then published asynchronously by a cron job. No messages are lost even if RabbitMQ is temporarily unavailable.
- **Exponential backoff retry**: Failed events are retried with increasing delays (`2^retry_count * 60` seconds) up to a configurable maximum before being dead-lettered.
- **Connection pooling**: Connections are cached at the registry level, surviving cron cycles and reducing connection overhead.
- **Multi-worker safety**: All cron jobs use `SELECT FOR UPDATE SKIP LOCKED` to prevent duplicate processing across Odoo workers.

### Cron jobs

| Job | Interval | Purpose |
|-----|----------|---------|
| Process Outbound Events | 1 min | Publish pending events to RabbitMQ |
| Process Inbound + Retry | 2 min | Consume messages and retry failed events |
| Cleanup Old Logs | 1 day | Remove old sent/received logs |

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `rabbitmq_connection_id` | localhost | Default RabbitMQ connection |
| `rabbitmq_publish_enabled` | `True` | Enable outbound publishing (cron) |
| `rabbitmq_global_hook_enabled` | `True` | Enable global BaseModel event capture |
| `rabbitmq_consume_enabled` | `True` | Enable inbound consuming |
| `rabbitmq_consumer_interval` | `2 min` | Consumer cron frequency |
| `rabbitmq_consumer_allow_delete` | `False` | Allow Delete action in field mapping consumers |
| `rabbitmq_log_retention_days` | `30` | Days to keep sent/received logs |
| `rabbitmq_max_retries` | `5` | Max retry attempts before dead-lettering |

### Connection settings

Connections support:
- Standard host/port/credentials configuration
- Full AMQP URI for complex setups (clusters, cloud providers)
- SSL/TLS with custom CA certificates
- Configurable heartbeat and connection timeouts
- Use the **Test Connection** button in the UI to verify connectivity

## Module structure

```
odoo_connector_rabbitmq/
├── hooks.py                             # Global BaseModel patch (post_load)
├── models/
│   ├── rabbitmq_connection.py           # Connection management + SSL/TLS
│   ├── rabbitmq_service.py              # Abstract service layer (pooling, publish, consume)
│   ├── rabbitmq_event_rule.py           # Event rule definitions + cache invalidation
│   ├── rabbitmq_consumer_rule.py        # Consumer rules + field mapping processor
│   ├── rabbitmq_consumer_field_mapping.py # Field mapping definitions
│   ├── rabbitmq_event_log.py            # Transactional outbox + cron jobs
│   ├── rabbitmq_event_bus_mixin.py      # Legacy auto event capture mixin
│   └── res_config_settings.py           # System settings
├── decorator.py                         # @rabbitmq_event decorator
├── views/                               # UI views and menus
├── security/                            # Access control (User / Manager groups)
├── data/                                # Default connection + cron definitions
└── docker-compose.yml                   # RabbitMQ container for development
```

## Security

Two access groups are provided:

| Group | Permissions |
|-------|-------------|
| **RabbitMQ User** | Read-only access to connections, rules, field mappings, and event logs |
| **RabbitMQ Manager** | Full CRUD access to all RabbitMQ models |

Additional safeguards:
- **Consumer Delete action** is disabled by default — must be explicitly enabled in Settings
- **Consumer rules validate** that the target model exists and the target method is present
- **Mapping constraints** enforce required fields (match field for update/upsert/delete actions)
- **All message processing** runs via `sudo()` under system context for reliable operation
- **Event logging** never blocks ORM operations — all wrapped in `try/except`

## Requirements

- Odoo 17.0, 18.0, or 19.0 (use the matching branch)
- Python 3.10+
- `pika >= 1.3.0`
- RabbitMQ 3.x

## Documentation

Full documentation is available at [https://tonybenoy.github.io/odoo_connector_rabbitmq/](https://tonybenoy.github.io/odoo_connector_rabbitmq/).

## License

This project is licensed under the [MIT License](LICENSE).
