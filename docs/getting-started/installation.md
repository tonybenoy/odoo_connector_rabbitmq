# Installation

## Prerequisites

- **Odoo 17.0**
- **Python 3.10+**
- **RabbitMQ 3.x** (see [Docker setup](../deployment/docker.md) for the easiest way to get started)

## Install the Python dependency

The module requires the `pika` library for AMQP communication:

```bash
pip install pika>=1.3.0
```

## Install the Odoo module

### Option 1: Copy to addons path

Copy the `odoo_connector_rabbitmq/` directory into your Odoo addons path:

```bash
cp -r odoo_connector_rabbitmq /path/to/odoo/addons/
```

Then restart Odoo and update the apps list:

```bash
odoo -u base -d your_database
```

### Option 2: Add to addons path config

Add the project directory to your `odoo.conf`:

```ini
[options]
addons_path = /path/to/odoo/addons,/path/to/odoo-connector-rabbitmq
```

### Option 3: Symlink

```bash
ln -s /path/to/odoo-connector-rabbitmq/odoo_connector_rabbitmq /path/to/odoo/addons/odoo_connector_rabbitmq
```

## Activate the module

1. Go to **Apps** in Odoo
2. Remove the "Apps" filter from the search bar
3. Search for **Odoo Connector RabbitMQ**
4. Click **Install**

## Start RabbitMQ

The fastest way to get RabbitMQ running locally:

```bash
docker compose -f odoo_connector_rabbitmq/docker-compose.yml up -d
```

This starts RabbitMQ with the management UI at [http://localhost:15672](http://localhost:15672) (guest/guest).

## Verify

After installation, navigate to the **RabbitMQ** menu in Odoo. You should see:

- **Dashboard** — event log overview
- **Configuration > Connections** — a default localhost connection is pre-configured

Click **Test Connection** on the default connection to verify connectivity.
