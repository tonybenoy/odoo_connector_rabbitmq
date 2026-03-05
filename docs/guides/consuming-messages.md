# Consuming Messages

Messages are consumed via **Consumer Rules**. There are two processing modes: **Field Mapping** (zero-code, recommended) and **Call Method** (legacy).

## Zero-Code: Field Mapping Mode (Recommended)

Process inbound messages without writing any Python code. The consumer maps JSON fields to Odoo fields and performs create/update/upsert/delete actions automatically.

### Setting up a field mapping consumer

1. Go to **RabbitMQ > Configuration > Consumer Rules > Create**
2. Set the **Queue**, **Exchange**, and **Binding Key**
3. Set **Target Model** (e.g. `res.partner`)
4. Choose **Processing Mode**: `Field Mapping`
5. Select an **Action**: `Create`, `Update`, `Create or Update`, or `Delete`
6. For update/upsert/delete, set the **Match Field** (e.g. `email`)
7. Optionally set **Payload Root** for nested JSON (e.g. `data.partner`)
8. Add **Field Mappings** in the table

### Field mapping configuration

Each mapping row defines how a JSON key maps to an Odoo field:

| Column | Description |
|--------|-------------|
| **Source Field** | JSON key from the payload (dot notation supported, e.g. `address.city`) |
| **Target Field** | Odoo field name on the target model |
| **Field Type** | How to convert the value (see below) |
| **Search Model** | For `Many2One (by Search)`: model to search in |
| **Search Field** | For `Many2One (by Search)`: field to match against |
| **Default Value** | Fallback if source field is missing or empty |

### Supported field types

| Type | Description | Example Input | Result |
|------|-------------|---------------|--------|
| Text | String conversion | `42` | `"42"` |
| Integer | Integer conversion | `"42"` | `42` |
| Float | Float conversion | `"3.14"` | `3.14` |
| Boolean | Boolean conversion | `"true"`, `1`, `"yes"` | `True` |
| Date | ISO date (first 10 chars) | `"2025-01-15T10:30:00Z"` | `"2025-01-15"` |
| Datetime | ISO datetime | `"2025-01-15T10:30:00Z"` | `"2025-01-15 10:30:00"` |
| Many2One (by ID) | Direct database ID | `5` | `5` |
| Many2One (by Search) | Search by field value | `"US"` | `ID of res.country where code='US'` |
| Raw | No conversion | `[1, 2, 3]` | `[1, 2, 3]` |

### Consumer actions

| Action | Behavior | Match Field Required? |
|--------|----------|-----------------------|
| **Create** | Creates a new record | No |
| **Update** | Updates an existing record (error if not found) | Yes |
| **Create or Update** | Updates if match found, creates otherwise | Yes |
| **Delete** | Deletes matching record (must be enabled in Settings) | Yes |

!!! warning
    The **Delete** action is disabled by default for safety. To enable it, go to **Settings > RabbitMQ > Consumer Safety > Allow Delete via Field Mapping**.

### Payload root

If your JSON message wraps the data in a nested structure, use **Payload Root** to navigate to it:

```json
{
    "meta": {"source": "external"},
    "data": {
        "partner": {
            "name": "John",
            "email": "john@example.com"
        }
    }
}
```

Set **Payload Root** to `data.partner` to extract the partner object.

### Example: Creating partners from JSON

Given this incoming message:

```json
{
    "first_name": "Jane",
    "last_name": "Doe",
    "email": "jane@example.com",
    "country_code": "US",
    "is_company": false
}
```

Configure these field mappings:

| Source Field | Target Field | Type | Search Model | Search Field |
|-------------|-------------|------|--------------|--------------|
| `first_name` | `name` | Text | | |
| `email` | `email` | Text | | |
| `country_code` | `country_id` | Many2One (by Search) | `res.country` | `code` |
| `is_company` | `is_company` | Boolean | | |

## Legacy: Call Method Mode

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

Then create a consumer rule with:

| Field | Value |
|-------|-------|
| **Processing Mode** | Call Method |
| **Target Model** | `order.processor` |
| **Target Method** | `handle_order` |

## How consumption works

1. The **inbound cron job** (every 2 minutes) iterates over all active consumer rules
2. For each rule, it calls `_consume_batch()` to pull up to `prefetch_count` messages
3. Each message is processed based on the processing mode:
    - **Field Mapping**: the consumer builds an Odoo vals dict from mappings and performs the configured action
    - **Call Method**: the message is passed to the target method
4. On success: the message is acknowledged and logged as `received`
5. On failure: the message is negative-acknowledged and requeued

```
Consumer Cron ──► Active Rules
                    │
                    ▼ (for each rule)
              _consume_batch(prefetch_count)
                    │
                    ▼ (for each message)
              ┌─────┴──────────────┐
              │                    │
         Field Mapping        Call Method
              │                    │
         build vals dict      target_method(body, props)
              │                    │
         create/write/         process
         upsert/unlink
              │                    │
              └─────┬──────────────┘
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

Exceptions in processing are caught by the consumer:

- The message is negative-acknowledged with `requeue=True`
- An inbound event log entry is created with state `failed`
- The error message is stored in the log for debugging
- The message returns to the queue for the next cron cycle

## Multiple consumers

You can create multiple consumer rules pointing to different queues or even the same queue with different routing keys. Each rule operates independently during the cron cycle.
