# @rabbitmq_event Decorator

The `@rabbitmq_event` decorator emits an event to the outbox after a method executes.

## Import

```python
from odoo.addons.odoo_connector_rabbitmq.decorator import rabbitmq_event
```

## Signature

```python
@rabbitmq_event(event_name, exchange='odoo_events', routing_key=None)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `event_name` | str | *required* | Event type name (e.g., `order_confirmed`) |
| `exchange` | str | `odoo_events` | Target exchange |
| `routing_key` | str | `None` | Custom routing key. Defaults to `{model}.{event_name}` |

## Behavior

1. The decorated method executes normally
2. After execution, the decorator creates an event log entry:
    - `event_id`: new UUID
    - `timestamp`: current UTC time (ISO 8601)
    - `database`: current database name
    - `model`: model name from `self._name`
    - `event_type`: the `event_name` parameter
    - `record_ids`: IDs from `self`
    - `user_id` / `user_login`: current user
    - `result`: method return value (if JSON-serializable)
    - `state`: `pending`
3. The event is published by the outbound cron job
4. Errors during event logging are caught and logged — **the method never fails due to event capture**

## Examples

### Basic usage

```python
from odoo.addons.odoo_connector_rabbitmq.decorator import rabbitmq_event

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @rabbitmq_event('order_confirmed')
    def action_confirm(self):
        return super().action_confirm()
```

This publishes to exchange `odoo_events` with routing key `sale.order.order_confirmed`.

### Custom exchange and routing key

```python
@rabbitmq_event('payment_received', exchange='payments', routing_key='payment.success')
def action_register_payment(self):
    # ...
```

### With return value capture

```python
@rabbitmq_event('invoice_posted')
def action_post(self):
    result = super().action_post()
    return result  # captured in the event payload as "result"
```

## Generated Payload

```json
{
    "event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "timestamp": "2025-01-15T10:30:00Z",
    "database": "odoo_production",
    "model": "sale.order",
    "event_type": "order_confirmed",
    "record_ids": [1, 2],
    "user_id": 2,
    "user_login": "admin",
    "result": true
}
```

## Notes

- The decorator works on any model method, not just lifecycle methods
- It does not interfere with the method's return value or exceptions
- Multiple decorators can be stacked on the same method
- The decorator uses the same outbox pattern as the mixin — events are published asynchronously by the cron job
