# Multi-Worker Safety

## The Challenge

Odoo typically runs with multiple workers (prefork mode). When a cron job triggers, multiple workers may attempt to process the same events simultaneously, leading to:

- **Duplicate publishing** — the same event published multiple times
- **Race conditions** — two workers updating the same event state
- **Lock contention** — workers blocking each other on row locks

## Solution: SELECT FOR UPDATE SKIP LOCKED

The module uses PostgreSQL's `SELECT FOR UPDATE SKIP LOCKED` to safely partition work across workers:

```sql
SELECT id FROM rabbitmq_event_log
WHERE state = 'pending' AND direction = 'outbound'
FOR UPDATE SKIP LOCKED
```

### How it works

1. **Worker A** starts the cron job, selects pending events, and locks them
2. **Worker B** starts the same cron job a moment later
3. Worker B's query sees the same pending events, but they are locked by Worker A
4. `SKIP LOCKED` causes Worker B to skip those rows entirely
5. Worker B either processes other unlocked rows or finishes with an empty set
6. No duplicate processing, no blocking, no contention

### Comparison with alternatives

| Approach | Behavior | Problem |
|----------|----------|---------|
| No locking | Both workers process same events | Duplicate messages |
| `FOR UPDATE` | Worker B blocks until A finishes | Wasted time, potential deadlocks |
| `FOR UPDATE NOWAIT` | Worker B gets an error immediately | Must handle errors, retry logic |
| **`FOR UPDATE SKIP LOCKED`** | Worker B skips locked rows silently | No issues |

## Connection Pooling

Connections are cached at the Odoo **registry** level (shared across workers within the same process):

```python
def _get_connection(self):
    registry = self.env.registry
    if not hasattr(registry, '_rabbitmq_connection') or \
       registry._rabbitmq_connection.is_closed:
        # Create new connection
        registry._rabbitmq_connection = pika.BlockingConnection(params)
    return registry._rabbitmq_connection
```

Benefits:

- Connections survive across cron invocations
- Reduced connection overhead (no connect/disconnect per cron cycle)
- Automatic reconnection on failure
- Heartbeats keep the connection alive (default: 600 seconds)

### Connection lifecycle

```
Worker Start
     │
     ▼
First cron run ──► Create connection ──► Cache in registry
     │
     ▼
Subsequent cron runs ──► Reuse cached connection
     │
     ▼
Connection drops ──► Auto-reconnect on next use
     │
     ▼
Worker shutdown ──► Connection closed with process
```

## Blocked Connection Handling

If RabbitMQ sends a `Connection.Blocked` frame (due to resource limits like memory or disk), the pika library's `BlockingConnection` handles this with a configurable timeout (300 seconds). The module will:

1. Wait for the block to clear
2. If the timeout expires, raise an exception
3. The event stays in `failed` state and is retried later

## Best Practices

!!! tip "Worker count"
    The number of Odoo workers doesn't affect correctness — `SKIP LOCKED` handles any number of concurrent workers. However, more workers means more connections to both PostgreSQL and RabbitMQ.

!!! tip "Cron intervals"
    The default intervals (1 min outbound, 2 min inbound) work well for most setups. Shorter intervals increase throughput but also increase database and broker load.
