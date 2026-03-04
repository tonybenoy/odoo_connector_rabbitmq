# Odoo Connector RabbitMQ

Production-grade event-driven architecture for Odoo 17.0 via RabbitMQ.

## Features

- **Transactional outbox pattern** for reliable message delivery
- **Automatic event capture** on create, write, unlink, and state changes via mixin
- **`@rabbitmq_event` decorator** for method-level event emission
- **Batch consumption** with configurable prefetch and manual acknowledgment
- **Retry with exponential backoff** and dead-letter handling
- **SSL/TLS** and cluster URI support
- **Connection pooling** with heartbeats and auto-reconnect
- **Multi-worker safe** using `SELECT FOR UPDATE SKIP LOCKED`
- **Monitoring UI** with event log viewer, filters, and grouping
- **Role-based access** (User / Manager groups)

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

### Automatic events via mixin

Inherit `rabbitmq.event.bus.mixin` and create Event Rules in the UI to capture model lifecycle events automatically.

```python
from odoo import models

class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'rabbitmq.event.bus.mixin']
```

Then create an **Event Rule** in the UI specifying:
- **Model**: `sale.order`
- **Event type**: `create`, `write`, `unlink`, `state_change`, or `custom`
- **Exchange / Routing key**: where to publish the event
- **Tracked fields** (optional): only emit events when specific fields change

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

### Consuming messages

Create a **Consumer Rule** pointing to a target model and method:

```python
import json
from odoo import models

class MyConsumer(models.Model):
    _name = 'my.consumer'

    def process_message(self, body, properties):
        data = json.loads(body)
        # handle the message
```

Then configure the Consumer Rule in the UI with:
- **Queue / Exchange / Routing key**: source to consume from
- **Target model**: `my.consumer`
- **Target method**: `process_message`
- **Prefetch count**: messages per batch (default 10)

## Architecture

```
Odoo Model ──► Event Rule / Decorator
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
           Consumer Rule ──► Target Method
```

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
| `rabbitmq_publish_enabled` | `True` | Enable outbound publishing |
| `rabbitmq_consume_enabled` | `True` | Enable inbound consuming |
| `rabbitmq_consumer_interval` | `2 min` | Consumer cron frequency |
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
├── models/
│   ├── rabbitmq_connection.py        # Connection management + SSL/TLS
│   ├── rabbitmq_service.py           # Abstract service layer (pooling, publish, consume)
│   ├── rabbitmq_event_rule.py        # Event rule definitions
│   ├── rabbitmq_consumer_rule.py     # Consumer rule definitions
│   ├── rabbitmq_event_log.py         # Transactional outbox + cron jobs
│   ├── rabbitmq_event_bus_mixin.py   # Auto event capture mixin
│   └── res_config_settings.py        # System settings
├── decorator.py                      # @rabbitmq_event decorator
├── views/                            # UI views and menus
├── security/                         # Access control (User / Manager groups)
├── data/                             # Default connection + cron definitions
└── docker-compose.yml                # RabbitMQ container for development
```

## Security

Two access groups are provided:

| Group | Permissions |
|-------|-------------|
| **RabbitMQ User** | Read-only access to event logs and monitoring |
| **RabbitMQ Manager** | Full access to connections, rules, and logs |

## Requirements

- Odoo 17.0
- Python 3.10+
- `pika >= 1.3.0`
- RabbitMQ 3.x

## Documentation

Full documentation is available at [https://tonybenoy.github.io/odoo_connector_rabbitmq/](https://tonybenoy.github.io/odoo_connector_rabbitmq/).

## License

This project is licensed under the [LGPL-3.0](LICENSE).
