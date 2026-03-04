# Odoo Connector RabbitMQ

Production-grade event-driven architecture for Odoo 17.0 via RabbitMQ.

## What is it?

**Odoo Connector RabbitMQ** is an Odoo 17.0 module that brings reliable, asynchronous messaging to your Odoo instance using RabbitMQ. It implements the **transactional outbox pattern** so no events are ever lost, even when RabbitMQ is temporarily unavailable.

## Key Features

- **Transactional outbox pattern** — events are stored atomically with your business data, then published asynchronously
- **Automatic event capture** — intercepts `create`, `write`, `unlink`, and state changes via a simple mixin
- **`@rabbitmq_event` decorator** — annotate any method to emit an event after execution
- **Batch consumption** — configurable prefetch count with manual acknowledgment
- **Retry with exponential backoff** — failed events are retried with increasing delays, then dead-lettered
- **SSL/TLS and cluster URI support** — connect to managed RabbitMQ services securely
- **Connection pooling** — cached connections with heartbeats and auto-reconnect
- **Multi-worker safe** — `SELECT FOR UPDATE SKIP LOCKED` prevents duplicate processing
- **Monitoring UI** — event log viewer with filters, grouping, and retry actions
- **Role-based access** — User (read-only) and Manager (full control) groups

## How It Works

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

Events are captured during normal model operations and stored in a local outbox table. A cron job publishes them to RabbitMQ asynchronously. On the consumer side, another cron job pulls messages from queues and dispatches them to target methods.

## Quick Links

- [Installation](getting-started/installation.md) — get up and running in minutes
- [Quick Start](getting-started/quickstart.md) — end-to-end example
- [Architecture Overview](architecture/overview.md) — understand the system design
- [API Reference](reference/models.md) — detailed model and method documentation
