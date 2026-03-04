# Cron Jobs Reference

The module registers three scheduled actions that run automatically.

## Process Outbound Events

| Property | Value |
|----------|-------|
| **XML ID** | `odoo_connector_rabbitmq.cron_process_outbound` |
| **Interval** | 1 minute |
| **Model** | `rabbitmq.event.log` |
| **Method** | `_process_pending_outbound()` |

Publishes pending outbound events to RabbitMQ:

1. Queries events with `state = 'pending'` and `direction = 'outbound'`
2. Locks rows with `SELECT FOR UPDATE SKIP LOCKED`
3. For each event, publishes to the configured exchange/routing key
4. On success: sets `state = 'sent'`
5. On failure: sets `state = 'failed'`, increments `retry_count`, calculates `next_retry_at`
6. After max retries: sets `state = 'dead'`

## Process Inbound + Retry Failed

| Property | Value |
|----------|-------|
| **XML ID** | `odoo_connector_rabbitmq.cron_process_inbound` |
| **Interval** | 2 minutes |
| **Model** | `rabbitmq.event.log` |
| **Method** | `_process_inbound()` + `_retry_failed_events()` |

### Inbound processing

1. Iterates all active `rabbitmq.consumer.rule` records
2. For each rule, consumes up to `prefetch_count` messages
3. Calls the target model's target method with `(body, properties)`
4. On success: acknowledges message, logs as `received`
5. On failure: negative-acknowledges with requeue, logs as `failed`

### Retry logic

1. Queries failed events where `next_retry_at <= now`
2. Resets their state to `pending` for the next outbound cycle
3. Events past `max_retries` are marked as `dead`

## Cleanup Old Logs

| Property | Value |
|----------|-------|
| **XML ID** | `odoo_connector_rabbitmq.cron_cleanup_logs` |
| **Interval** | 1 day |
| **Model** | `rabbitmq.event.log` |
| **Method** | `_cleanup_old_logs()` |

Deletes event logs older than the configured retention period:

- Only removes events with state `sent` or `received`
- Retention period: `odoo_connector_rabbitmq.log_retention_days` (default: 30 days)
- Events with state `pending`, `failed`, or `dead` are never cleaned up

## Common Properties

All cron jobs share:

| Property | Value |
|----------|-------|
| `numbercall` | `-1` (run indefinitely) |
| `active` | `True` |
| `priority` | `5` |

## Managing Cron Jobs

Cron jobs can be managed at **Settings > Technical > Automation > Scheduled Actions**.

!!! tip
    You can trigger any cron job manually by opening it and clicking **Run Manually**. This is useful for testing or processing a backlog of events without waiting for the next scheduled run.
