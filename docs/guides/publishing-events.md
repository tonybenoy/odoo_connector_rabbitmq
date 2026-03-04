# Publishing Events

There are two ways to publish events: the **mixin** for automatic lifecycle capture, and the **`@rabbitmq_event` decorator** for explicit method-level emission.

## Mixin Approach

Inherit `rabbitmq.event.bus.mixin` on any model to enable automatic event capture:

```python
from odoo import models

class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'rabbitmq.event.bus.mixin']
```

Then create **Event Rules** in the UI (**RabbitMQ > Configuration > Event Rules**) to define which events to capture.

### Supported event types

| Event Type | Trigger | Captured Data |
|------------|---------|---------------|
| `create` | Record creation | New field values |
| `write` | Record update | Changed values + old values |
| `unlink` | Record deletion | Snapshot of deleted records |
| `state_change` | State field transition | Old state, new state, transition details |
| `custom` | Manual trigger | Custom payload |

### Tracking specific fields

For `write` events, you can select specific fields to track. Events are only emitted when one of the tracked fields changes. Leave the field list empty to track all fields.

### State change events

State change events fire when a designated state field transitions from one value to another. Configure the **State Field** on the event rule (default: `state`).

The payload includes transition details:

```json
{
    "state_transition": {
        "field": "state",
        "from": "draft",
        "to": "sale"
    }
}
```

### Routing keys

Routing keys support placeholders:

- `{model}` — replaced with the model name (dots replaced with underscores)
- `{event}` — replaced with the event type

Example: `{model}.{event}` becomes `sale_order.create`.

## Decorator Approach

Use `@rabbitmq_event` to emit an event when a specific method executes:

```python
from odoo.addons.odoo_connector_rabbitmq.decorator import rabbitmq_event

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @rabbitmq_event('order_confirmed', exchange='sales', routing_key='order.confirmed')
    def action_confirm(self):
        return super().action_confirm()
```

The decorator:

1. Executes the original method normally
2. Captures the return value (if JSON-serializable)
3. Creates an event log entry with state `pending`
4. Never interferes with the method — errors in event logging are caught and logged

See the [Decorator Reference](../reference/decorator.md) for full API details.

## Payload Structure

All events follow a standardized payload format:

```json
{
    "event_id": "uuid",
    "timestamp": "2025-01-15T10:30:00Z",
    "database": "odoo_db",
    "model": "sale.order",
    "event_type": "create",
    "record_ids": [1, 2, 3],
    "user_id": 2,
    "user_login": "admin",
    "values": {}
}
```

Additional fields vary by event type:

| Event Type | Extra Fields |
|------------|-------------|
| `create` | `values` |
| `write` | `values`, `old_values`, `changed_fields` |
| `unlink` | `deleted_records` |
| `state_change` | `old_values`, `state_transition` |
| decorator | `result` (method return value) |

## Mixin vs Decorator

| Aspect | Mixin | Decorator |
|--------|-------|-----------|
| Configuration | UI-driven (Event Rules) | Code-driven |
| Scope | Model lifecycle events | Any method |
| Flexibility | Configurable at runtime | Fixed at deploy time |
| Use case | Standard CRUD tracking | Business logic events |

!!! tip
    Use both together — the mixin for CRUD tracking and the decorator for business-specific events like order confirmation or payment processing.
