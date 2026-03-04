# Configuration

## Connection Setup

Navigate to **RabbitMQ > Configuration > Connections** to manage RabbitMQ connections.

A default localhost connection is created on module installation:

| Field | Default |
|-------|---------|
| Host | `localhost` |
| Port | `5672` |
| Username | `guest` |
| Password | `guest` |
| Virtual Host | `/` |

### Connection URI

For complex setups (clusters, cloud providers), use the **Connection URI** field instead of individual fields:

```
amqp://user:password@host:5672/vhost
```

When a URI is provided, it takes precedence over the individual host/port/credentials fields.

### SSL/TLS

Enable **SSL/TLS** and optionally upload a CA certificate for secure connections. This is required for most managed RabbitMQ services (CloudAMQP, Amazon MQ, etc.).

### Connection parameters

| Field | Default | Description |
|-------|---------|-------------|
| Heartbeat | `600` seconds | Keep-alive interval |
| Connection Timeout | `10` seconds | Max time to establish connection |

Use **Test Connection** to verify your settings.

## System Settings

Navigate to **Settings > RabbitMQ** to configure module-wide behavior.

| Setting | Default | Description |
|---------|---------|-------------|
| Default Connection | localhost | Which connection to use for publishing/consuming |
| Publishing Enabled | `True` | Enable outbound event publishing |
| Consuming Enabled | `True` | Enable inbound message consuming |
| Consumer Interval | `2` minutes | How often the consumer cron runs |
| Log Retention | `30` days | How long to keep sent/received event logs |
| Max Retries | `5` | Retry attempts before dead-lettering |

### Configuration parameters

These settings are stored as `ir.config_parameter` records:

| Key | Type | Default |
|-----|------|---------|
| `odoo_connector_rabbitmq.default_connection_id` | Integer | `1` |
| `odoo_connector_rabbitmq.publish_enabled` | Boolean | `True` |
| `odoo_connector_rabbitmq.consume_enabled` | Boolean | `True` |
| `odoo_connector_rabbitmq.consumer_interval` | Integer | `2` |
| `odoo_connector_rabbitmq.log_retention_days` | Integer | `30` |
| `odoo_connector_rabbitmq.max_retries` | Integer | `5` |

!!! tip
    Disable publishing temporarily during data migrations to avoid flooding RabbitMQ with events.
