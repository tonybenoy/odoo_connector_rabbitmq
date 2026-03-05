# Architecture Overview

## System Design

The Odoo Connector RabbitMQ module follows a decoupled, event-driven architecture with the **transactional outbox pattern** at its core.

```
┌─────────────────────────────────────────────────────────┐
│                        Odoo                             │
│                                                         │
│  ┌──────────────┐    ┌──────────────┐                   │
│  │  Any Model   │    │  Your Model  │                   │
│  │ (Global Hook)│    │  + Decorator │                   │
│  └──────┬───────┘    └──────┬───────┘                   │
│         │                   │                           │
│         ▼                   ▼                           │
│  ┌──────────────────────────────────┐                   │
│  │       rabbitmq.event.log        │  ◄── Outbox Table  │
│  │  (pending → sent/failed/dead)   │                    │
│  └──────────────┬──────────────────┘                    │
│                 │                                       │
│  ┌──────────────┴──────────────────┐                    │
│  │     rabbitmq.service            │  ◄── Service Layer │
│  │  (connection pool, publish,     │                    │
│  │   consume, ack/nack)            │                    │
│  └──────────────┬──────────────────┘                    │
│                 │                                       │
└─────────────────┼───────────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────┐
│         RabbitMQ Broker             │
│                                     │
│  Exchanges ──► Queues ──► Consumers │
└─────────────────────────────────────┘
```

## Components

### Event Capture Layer

Three mechanisms capture events:

- **Global Hook (`post_load`)** — patches `BaseModel.create`, `write`, `unlink` at module load time. Checks a fast in-memory rules cache on every ORM call. Zero overhead for models without rules (~3 dict lookups). Configured via Event Rules in the UI — **no code needed**.
- **Legacy Mixin (`rabbitmq.event.bus.mixin`)** — intercepts `create`, `write`, `unlink` at the ORM level. Kept for backward compatibility. Models using the mixin are automatically skipped by the global hook.
- **Decorator (`@rabbitmq_event`)** — wraps any method to emit an event after execution. Configured in code.

All three produce entries in the `rabbitmq.event.log` table with state `pending`.

### Consumer Layer

Two processing modes for consuming messages:

- **Field Mapping (zero-code)** — maps JSON fields to Odoo fields via UI configuration. Supports create, update, upsert, and delete actions with type conversion and many2one lookups.
- **Call Method (legacy)** — dispatches messages to a Python method on a target model.

### Outbox Table

The `rabbitmq.event.log` model serves as a transactional outbox:

- Events are written atomically with the business transaction
- No network I/O during the request — publishing is deferred
- Acts as an audit trail of all events

### Service Layer

`rabbitmq.service` is an abstract model providing:

- **Connection pooling** — cached at the registry level
- **Channel management** — with publisher confirms
- **Exchange/queue declaration** — idempotent setup
- **Publish/consume** — with proper error handling
- **Ack/nack** — message acknowledgment

### Cron Jobs

Three cron jobs drive the system:

| Job | Interval | Responsibility |
|-----|----------|----------------|
| Outbound processor | 1 min | Publish pending events |
| Inbound processor + retry | 2 min | Consume messages, retry failed events |
| Log cleanup | 1 day | Remove old sent/received logs |

### Configuration

- **Connections** — RabbitMQ server details (host, SSL, URI)
- **Event Rules** — which models/events to capture (zero code)
- **Consumer Rules** — which queues to consume and how to process messages (zero code with field mapping)
- **System Settings** — global toggles and parameters

## Data Flow

### Outbound (Publishing)

```
1. User creates/updates/deletes a record
2. Global hook intercepts the ORM call
3. Rules cache is checked (fast dict lookup by model name)
4. If rules exist: payload is built (standardized JSON)
5. Event log entry created (state=pending) — same DB transaction
6. Transaction commits — event is guaranteed persisted
7. [Cron: 1 min] Picks up pending events (SKIP LOCKED)
8. Publishes to RabbitMQ via service layer
9. On success: state=sent | On failure: state=failed + backoff
```

### Inbound (Consuming)

```
1. [Cron: 2 min] Iterates active consumer rules
2. Consumes batch from each queue (up to prefetch_count)
3. For each message:
   Field Mapping mode:
     a. Parses JSON, navigates to payload root
     b. Builds vals dict from field mappings
     c. Performs action (create/write/upsert/unlink)
   Call Method mode:
     a. Calls target_model.target_method(body, properties)
   b. On success: ack + log as received
   c. On failure: nack + requeue + log as failed
```

## Rules Cache

The global hook maintains an in-memory cache on the registry (`registry._rabbitmq_rules_cache`), structured as:

```python
{
    "res.partner": {
        "create": [{"id": 1, "exchange_name": "odoo_events", ...}],
        "write": [{"id": 2, ...}],
    },
    "sale.order": {
        "state_change": [{"id": 3, ...}],
    },
}
```

- **Rebuilt lazily** on the first ORM call after invalidation
- **Invalidated automatically** when Event Rules are created, modified, or deleted, or when Settings are saved
- **Zero overhead** for models not in the cache (1 attr access + 1 dict `in` check)
- **Pre-computed frozensets** for tracked field names — set intersection is O(min(n,m)) with no allocation
- **Disableable** via Settings > RabbitMQ > Enable Global Hook (builds empty cache when disabled)

## Key Design Decisions

### Why a global hook instead of requiring mixin inheritance?

The mixin approach requires writing Python code for every model. The global hook enables true zero-code configuration — just create Event Rules in the UI and they take effect immediately.

### Why an outbox instead of direct publishing?

Direct publishing during an HTTP request means:

- If RabbitMQ is down, the request fails
- If the request fails after publishing, the event is sent but the data isn't committed
- Network latency is added to every request

The outbox pattern solves all three: events are committed with the data, published asynchronously, and retried automatically.

### Why cron jobs instead of background threads?

Odoo's architecture uses prefork workers that are managed by the framework. Background threads can cause issues with database connections and transactions. Cron jobs integrate naturally with Odoo's worker model and transaction management.

### Why SKIP LOCKED?

Multiple Odoo workers may run the same cron job simultaneously. `SELECT FOR UPDATE SKIP LOCKED` ensures each worker processes different events without blocking or duplicate processing. See [Multi-Worker Safety](multi-worker-safety.md).
