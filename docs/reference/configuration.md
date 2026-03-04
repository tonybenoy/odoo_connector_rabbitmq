# Configuration Reference

All module settings are accessible via **Settings > RabbitMQ** and stored as `ir.config_parameter` records.

## System Parameters

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `odoo_connector_rabbitmq.default_connection_id` | Integer | `1` | ID of the default `rabbitmq.connection` record |
| `odoo_connector_rabbitmq.publish_enabled` | Boolean | `True` | Enable outbound event publishing |
| `odoo_connector_rabbitmq.consume_enabled` | Boolean | `True` | Enable inbound message consuming |
| `odoo_connector_rabbitmq.consumer_interval` | Integer | `2` | Consumer cron interval in minutes |
| `odoo_connector_rabbitmq.log_retention_days` | Integer | `30` | Days to retain sent/received event logs |
| `odoo_connector_rabbitmq.max_retries` | Integer | `5` | Maximum retry attempts before dead-lettering |

## Settings Model Fields

The `res.config.settings` model exposes these fields:

| Field | Type | Config Parameter |
|-------|------|-----------------|
| `rabbitmq_connection_id` | Many2one → `rabbitmq.connection` | `odoo_connector_rabbitmq.default_connection_id` |
| `rabbitmq_publish_enabled` | Boolean | `odoo_connector_rabbitmq.publish_enabled` |
| `rabbitmq_consume_enabled` | Boolean | `odoo_connector_rabbitmq.consume_enabled` |
| `rabbitmq_consumer_interval` | Integer | `odoo_connector_rabbitmq.consumer_interval` |
| `rabbitmq_log_retention_days` | Integer | `odoo_connector_rabbitmq.log_retention_days` |
| `rabbitmq_max_retries` | Integer | `odoo_connector_rabbitmq.max_retries` |

## Connection Fields

Each `rabbitmq.connection` record has:

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `name` | Char | *required* | Display name |
| `connection_uri` | Char | | Full AMQP URI — overrides host/port/credentials |
| `host` | Char | `localhost` | RabbitMQ server hostname |
| `port` | Integer | `5672` | AMQP port |
| `username` | Char | `guest` | Auth username |
| `password` | Char | `guest` | Auth password |
| `virtual_host` | Char | `/` | RabbitMQ vhost |
| `ssl_enabled` | Boolean | `False` | Enable SSL/TLS |
| `ssl_ca_cert` | Binary | | CA certificate file |
| `heartbeat` | Integer | `600` | Heartbeat interval (seconds) |
| `connection_timeout` | Integer | `10` | Connection timeout (seconds) |

## Default Connection Data

On module installation, a default connection is created:

```xml
<record id="default_connection" model="rabbitmq.connection">
    <field name="name">Default (localhost)</field>
    <field name="host">localhost</field>
    <field name="port">5672</field>
    <field name="username">guest</field>
    <field name="password">guest</field>
    <field name="virtual_host">/</field>
</record>
```

## Retry Configuration

| Parameter | Value | Formula |
|-----------|-------|---------|
| Backoff delay | `2^retry_count × 60s` | Exponential |
| Retry 1 | 2 minutes | `2^1 × 60` |
| Retry 2 | 4 minutes | `2^2 × 60` |
| Retry 3 | 8 minutes | `2^3 × 60` |
| Retry 4 | 16 minutes | `2^4 × 60` |
| Retry 5 | 32 minutes | `2^5 × 60` |
| Total max wait | ~62 minutes | Sum of all delays |
