# Quick Start

This guide walks you through publishing your first event and consuming it — end to end.

## Prerequisites

- Odoo Connector RabbitMQ [installed](installation.md)
- RabbitMQ running (see [Docker setup](../deployment/docker.md))
- Connection verified via **Test Connection** in the UI

## Step 1: Create a publisher

Add the mixin to a model you want to track. In a custom module:

```python
from odoo import models

class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = ['res.partner', 'rabbitmq.event.bus.mixin']
```

## Step 2: Create an event rule

Go to **RabbitMQ > Configuration > Event Rules** and create a new rule:

| Field | Value |
|-------|-------|
| Name | Partner Created |
| Model | `res.partner` |
| Event Type | `create` |
| Exchange | `odoo_events` |
| Exchange Type | `topic` |
| Routing Key | `partner.created` |

## Step 3: Create a consumer

In your custom module, create a model to handle incoming messages:

```python
import json
import logging
from odoo import models

_logger = logging.getLogger(__name__)

class PartnerConsumer(models.Model):
    _name = 'partner.consumer'
    _description = 'Partner Event Consumer'

    def process_partner_event(self, body, properties):
        data = json.loads(body)
        _logger.info(
            "New partner created: IDs=%s, by user=%s",
            data['record_ids'],
            data['user_login'],
        )
```

## Step 4: Create a consumer rule

Go to **RabbitMQ > Configuration > Consumer Rules** and create:

| Field | Value |
|-------|-------|
| Name | Partner Event Consumer |
| Queue | `partner_events` |
| Exchange | `odoo_events` |
| Routing Key | `partner.created` |
| Target Model | `partner.consumer` |
| Target Method | `process_partner_event` |
| Prefetch Count | `10` |

## Step 5: Test it

1. Create a new contact in Odoo
2. Go to **RabbitMQ > Dashboard** — you should see a new outbound event with state **Pending**
3. Wait for the outbound cron (runs every 1 minute) — the event state changes to **Sent**
4. Wait for the inbound cron (runs every 2 minutes) — an inbound event appears with state **Received**
5. Check your Odoo logs for the consumer output

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

- [Publishing Events](../guides/publishing-events.md) — mixin and decorator approaches
- [Consuming Messages](../guides/consuming-messages.md) — consumer rules and target methods
- [Retry & Dead Letter](../guides/retry-and-dead-letter.md) — error handling
