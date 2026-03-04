# Retry & Dead Letter

The module implements automatic retry with exponential backoff for failed outbound events.

## Retry flow

```
Event fails to publish
        │
        ▼
  state = 'failed'
  retry_count += 1
  next_retry_at = now + backoff
        │
        ▼
  Retry cron checks next_retry_at
        │
  ┌─────┴─────┐
  │            │
past due    not yet
  │            │
  ▼            (skip)
state = 'pending'
  │
  ▼
Outbound cron retries publish
  │
  ┌─────┴─────┐
  │            │
success     failure
  │            │
  ▼            ▼
'sent'    retry_count < max?
              │
        ┌─────┴─────┐
        │            │
       yes          no
        │            │
        ▼            ▼
    backoff       'dead'
```

## Exponential backoff

The delay between retries increases exponentially:

```
Delay = 2^retry_count × 60 seconds
```

| Retry | Delay |
|-------|-------|
| 1 | 2 minutes |
| 2 | 4 minutes |
| 3 | 8 minutes |
| 4 | 16 minutes |
| 5 | 32 minutes |

After the maximum number of retries (default: 5), the event is marked as **dead**.

## Configuring retries

Set the maximum retry count in **Settings > RabbitMQ**:

| Setting | Default | Config Key |
|---------|---------|------------|
| Max Retries | `5` | `odoo_connector_rabbitmq.max_retries` |

## Dead-lettered events

Events that exhaust all retries are marked with state `dead`. They remain in the event log for inspection.

### Manual retry

To retry dead events:

1. Go to **RabbitMQ > Monitoring > Event Log**
2. Filter by state **Dead**
3. Select the event(s) and click **Retry** to reset them to `pending`

Or use the **Retry All Dead** action to reset all dead events at once.

!!! warning
    Before retrying dead events, investigate the root cause. Common causes include:

    - RabbitMQ connection issues (check the connection status)
    - Exchange or queue not declared
    - Payload serialization errors
    - Network timeouts

### Programmatic retry

```python
# Retry a single event
event = self.env['rabbitmq.event.log'].browse(event_id)
event.action_retry()

# Retry all dead events
self.env['rabbitmq.event.log'].action_retry_all_dead()
```

## Monitoring

The **Dashboard** view groups events by state, giving you an at-a-glance view of:

- **Pending** — awaiting publication
- **Sent** — successfully published
- **Failed** — will be retried
- **Dead** — exhausted retries, needs manual intervention
- **Received** — successfully consumed

!!! tip
    Set up Odoo email alerts or automated actions on the `rabbitmq.event.log` model to get notified when events are dead-lettered.
