# Consuming Messages

Messages are consumed via **Consumer Rules** that bind a RabbitMQ queue to a target Odoo model and method.

## Creating a consumer

### 1. Define the target method

Create a method on any Odoo model that accepts `body` and `properties`:

```python
import json
from odoo import models

class OrderProcessor(models.Model):
    _name = 'order.processor'
    _description = 'Order Event Processor'

    def handle_order(self, body, properties):
        data = json.loads(body)
        order_ids = data.get('record_ids', [])

        for order_id in order_ids:
            # Process each order
            self.env['sale.order'].browse(order_id).action_do_something()
```

**Parameters:**

- `body` (str) — the raw message body (typically JSON)
- `properties` (pika.BasicProperties) — AMQP message properties (content type, headers, etc.)

### 2. Create a consumer rule

Go to **RabbitMQ > Configuration > Consumer Rules** and configure:

| Field | Description |
|-------|-------------|
| **Name** | Descriptive name for the rule |
| **Queue Name** | RabbitMQ queue to consume from |
| **Exchange Name** | Exchange to bind the queue to (optional) |
| **Routing Key** | Binding key for the queue-exchange binding |
| **Target Model** | Odoo model containing the handler method |
| **Target Method** | Method name to invoke for each message |
| **Prefetch Count** | Max messages to consume per cron cycle (default: 10) |
| **Auto Ack** | Acknowledge messages automatically after method call |

## How consumption works

1. The **inbound cron job** (every 2 minutes) iterates over all active consumer rules
2. For each rule, it calls `_consume_batch()` to pull up to `prefetch_count` messages
3. Each message is passed to the target method
4. On success: the message is acknowledged and logged as `received`
5. On failure: the message is negative-acknowledged and requeued

```
Consumer Cron ──► Active Rules
                    │
                    ▼ (for each rule)
              _consume_batch(prefetch_count)
                    │
                    ▼ (for each message)
              target_model.target_method(body, properties)
                    │
              ┌─────┴─────┐
              │            │
           success      failure
              │            │
           ack msg     nack + requeue
```

## Prefetch count

The `prefetch_count` controls how many messages are pulled from the queue in a single cron cycle. This acts as a natural rate limiter:

- **Low values (1-5):** Safer for slow or resource-intensive processing
- **Default (10):** Good balance for most use cases
- **High values (50+):** Higher throughput but longer cron execution time

!!! warning
    Keep prefetch count reasonable. Each message is processed synchronously within the cron job. Very high values can cause the cron to run for too long and block other scheduled actions.

## Auto-acknowledge

When **Auto Ack** is enabled, messages are acknowledged immediately after the target method returns, regardless of whether it raised an exception.

When disabled (default), acknowledgment happens only after successful processing. Failed messages are negative-acknowledged and requeued for retry.

!!! tip
    Leave auto-ack disabled for most use cases. This ensures messages are not lost if processing fails.

## Error handling

Exceptions in the target method are caught by the consumer:

- The message is negative-acknowledged with `requeue=True`
- An inbound event log entry is created with state `failed`
- The error message is stored in the log for debugging
- The message returns to the queue for the next cron cycle

## Multiple consumers

You can create multiple consumer rules pointing to different queues or even the same queue with different routing keys. Each rule operates independently during the cron cycle.
