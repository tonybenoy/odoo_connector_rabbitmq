# Transactional Outbox Pattern

## The Problem

In a distributed system, you need to both update local data and send a message to a broker. These are two separate operations that can fail independently:

```
# Naive approach — unreliable
def create(self, vals_list):
    records = super().create(vals_list)
    rabbitmq.publish(event)  # What if this fails?
    return records            # Data saved, but event lost

# Or worse:
def create(self, vals_list):
    rabbitmq.publish(event)  # Published!
    records = super().create(vals_list)  # What if THIS fails?
    return records            # Event sent, but data not saved
```

Neither ordering is safe. You cannot achieve atomicity across a database transaction and a network call without a coordination protocol.

## The Solution

The **transactional outbox pattern** writes the event to a local database table within the same transaction as the business data:

```
def create(self, vals_list):
    records = super().create(vals_list)
    self.env['rabbitmq.event.log'].create({
        'payload': json.dumps(event),
        'state': 'pending',
        ...
    })
    # Both writes are in the SAME transaction
    return records
```

A separate process (cron job) reads pending events and publishes them to RabbitMQ:

```
# Cron job (every 1 minute)
def _process_pending_outbound(self):
    events = self.search([('state', '=', 'pending')])
    for event in events:
        try:
            rabbitmq.publish(event.payload)
            event.state = 'sent'
        except Exception:
            event.state = 'failed'
```

## Implementation in This Module

### 1. Event Capture

The mixin overrides `create`, `write`, and `unlink` to log events:

```python
class RabbitMQEventBusMixin(models.AbstractModel):
    _name = 'rabbitmq.event.bus.mixin'

    def create(self, vals_list):
        records = super().create(vals_list)
        for rule in self._rmq_get_rules('create'):
            payload = self._rmq_prepare_payload('create', records, vals=vals_list)
            self._rmq_log_event(rule, payload)
        return records
```

The event log entry is created in the same transaction. If the transaction rolls back, the event is also rolled back — consistency is guaranteed.

### 2. Asynchronous Publishing

The outbound cron job processes pending events:

```python
def _process_pending_outbound(self):
    # Lock rows to prevent duplicate processing
    self.env.cr.execute("""
        SELECT id FROM rabbitmq_event_log
        WHERE state = 'pending' AND direction = 'outbound'
        FOR UPDATE SKIP LOCKED
    """)
    # Publish each event...
```

### 3. Retry with Backoff

Failed events are retried with exponential backoff:

```
Delay = 2^retry_count × 60 seconds
```

After `max_retries` attempts, events are marked as `dead` for manual inspection.

### 4. Cleanup

Old sent/received events are cleaned up daily based on the retention period.

## Guarantees

| Guarantee | Provided? | How |
|-----------|-----------|-----|
| **At-least-once delivery** | Yes | Retry until sent or dead-lettered |
| **No lost events** | Yes | Atomic write with business data |
| **No phantom events** | Yes | Rolls back with failed transactions |
| **Ordering** | Best-effort | Events processed in creation order, but concurrent workers may interleave |
| **Exactly-once delivery** | No | Consumers should be idempotent |

!!! warning "Consumers must be idempotent"
    The outbox guarantees at-least-once delivery, which means a message may be delivered more than once (e.g., if the cron publishes successfully but crashes before marking the event as sent). Design your consumers to handle duplicate messages safely.

## Trade-offs

| Aspect | Trade-off |
|--------|-----------|
| **Latency** | Events are not published instantly — there's up to a 1-minute delay (cron interval) |
| **Storage** | Events are stored in the database until published and cleaned up |
| **Complexity** | More moving parts than direct publishing |
| **Reliability** | Significantly more reliable than direct publishing |

The latency trade-off is acceptable for most Odoo use cases, where near-real-time (seconds) is sufficient and strict real-time is not required.
