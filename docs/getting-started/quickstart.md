# Quick Start

This guide walks you through publishing your first event and consuming it — end to end, with zero code.

## Prerequisites

- Odoo Connector RabbitMQ [installed](installation.md)
- RabbitMQ running (see [Docker setup](../deployment/docker.md))
- Connection verified via **Test Connection** in the UI

## Step 1: Create a connection

Go to **RabbitMQ > Configuration > Connections** and create:

| Field | Value |
|-------|-------|
| Name | `Local RabbitMQ` |
| Host | `rabbitmq` (or `localhost`) |
| Port | `5672` |
| Username | `guest` |
| Password | `guest` |

Click **Test Connection** to verify.

Then go to **RabbitMQ > Configuration > Settings** and set it as the **Default Connection**.

## Step 2: Create an event rule

Go to **RabbitMQ > Configuration > Event Rules** and create a new rule:

| Field | Value |
|-------|-------|
| Name | `Partner Events` |
| Model | `res.partner` |
| On Create | checked |
| On Update | checked |
| On Delete | checked |
| Exchange | `odoo_events` |
| Exchange Type | `topic` |
| Routing Key | `odoo.{model}.{event}` |

That's it — no Python code needed. The global hook will automatically capture create, update, and delete operations on `res.partner`.

!!! tip
    Use `{model}` and `{event}` placeholders in routing keys. They resolve to values like `odoo.res.partner.create`, `odoo.res.partner.write`, etc.

## Step 3: Create a consumer rule (zero-code)

Go to **RabbitMQ > Configuration > Consumer Rules** and create:

| Field | Value |
|-------|-------|
| Name | `Sync Partner Notes` |
| Queue | `partner_events` |
| Exchange | `odoo_events` |
| Routing Key | `odoo.res.partner.create` |
| Target Model | `res.partner` |
| Processing Mode | **Field Mapping** |
| Action | **Create** |

Then add field mappings:

| Source Field (JSON) | Target Field (Odoo) | Type |
|---------------------|---------------------|------|
| `values.name` | `name` | Text |
| `values.email` | `email` | Text |
| `values.phone` | `phone` | Text |

## Step 4: Test it

1. Create a new contact in Odoo
2. Go to **RabbitMQ > Dashboard** — you should see a new outbound event with state **Pending**
3. Wait for the outbound cron (runs every 1 minute) — the event state changes to **Sent**
4. Wait for the inbound cron (runs every 2 minutes) — an inbound event appears with state **Received**

!!! tip
    You can trigger cron jobs manually from **Settings > Technical > Automation > Scheduled Actions** to skip the wait.

## Event payload

The published event looks like this:

```json
{
    "event_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "timestamp": "2025-01-15T10:30:00Z",
    "database": "odoo_production",
    "model": "res.partner",
    "event_type": "create",
    "record_ids": [42],
    "user_id": 2,
    "user_login": "admin",
    "values": {
        "name": "Acme Corp",
        "email": "info@acme.com"
    }
}
```

## Next steps

- [Publishing Events](../guides/publishing-events.md) — advanced publishing with field tracking, state changes, and the `@rabbitmq_event` decorator
- [Consuming Messages](../guides/consuming-messages.md) — field mapping types, match fields, and the Call Method mode
- [Retry & Dead Letter](../guides/retry-and-dead-letter.md) — error handling and monitoring
