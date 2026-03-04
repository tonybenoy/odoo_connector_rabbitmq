# Docker Setup

## Quick Start

The module includes a Docker Compose file for running RabbitMQ locally:

```bash
docker compose -f odoo_connector_rabbitmq/docker-compose.yml up -d
```

This starts:

- **RabbitMQ** on port `5672` (AMQP)
- **Management UI** on port `15672` (HTTP)

## Docker Compose Configuration

```yaml
version: '3.8'

services:
  rabbitmq:
    image: rabbitmq:3-management
    container_name: odoo-connector-rabbitmq
    ports:
      - "5672:5672"
      - "15672:15672"
    environment:
      RABBITMQ_DEFAULT_USER: guest
      RABBITMQ_DEFAULT_PASS: guest
    volumes:
      - rabbitmq_data:/var/lib/rabbitmq
    restart: unless-stopped

volumes:
  rabbitmq_data:
```

## Management UI

Access the RabbitMQ Management Console at [http://localhost:15672](http://localhost:15672):

- **Username:** `guest`
- **Password:** `guest`

The management UI lets you:

- Monitor queues, exchanges, and bindings
- View message rates and connection status
- Manually publish and consume messages for testing
- Manage users and virtual hosts

## Customizing

### Change credentials

```yaml
environment:
  RABBITMQ_DEFAULT_USER: myuser
  RABBITMQ_DEFAULT_PASS: mypassword
```

Update the Odoo connection settings to match.

### Change ports

```yaml
ports:
  - "5673:5672"    # Map to different host port
  - "15673:15672"
```

### Add a custom configuration file

```yaml
volumes:
  - rabbitmq_data:/var/lib/rabbitmq
  - ./rabbitmq.conf:/etc/rabbitmq/rabbitmq.conf
```

### Enable additional plugins

```yaml
environment:
  RABBITMQ_DEFAULT_USER: guest
  RABBITMQ_DEFAULT_PASS: guest
  RABBITMQ_PLUGINS: "rabbitmq_management rabbitmq_shovel rabbitmq_shovel_management"
```

## Persistent Storage

The `rabbitmq_data` volume ensures messages and configuration survive container restarts. To reset RabbitMQ completely:

```bash
docker compose -f odoo_connector_rabbitmq/docker-compose.yml down -v
docker compose -f odoo_connector_rabbitmq/docker-compose.yml up -d
```

!!! warning
    The `-v` flag removes volumes, deleting all messages and configuration. Use with caution.

## Verifying the Setup

Check that RabbitMQ is running:

```bash
docker compose -f odoo_connector_rabbitmq/docker-compose.yml ps
```

Then in Odoo, go to **RabbitMQ > Configuration > Connections** and click **Test Connection** on the default localhost connection.
