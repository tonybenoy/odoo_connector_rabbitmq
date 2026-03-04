# Security

## Access Groups

The module provides two security groups under the **RabbitMQ** category:

### RabbitMQ User

- **XML ID:** `odoo_connector_rabbitmq.group_rabbitmq_user`
- **Implied by:** `base.group_user` (all internal users)
- **Permissions:** Read-only access to all RabbitMQ models

Grants access to:

- Dashboard and monitoring views
- Event log viewer (read-only)
- Connection, event rule, and consumer rule lists (read-only)

### RabbitMQ Manager

- **XML ID:** `odoo_connector_rabbitmq.group_rabbitmq_manager`
- **Implies:** `group_rabbitmq_user`
- **Default members:** Administrator
- **Permissions:** Full CRUD on all RabbitMQ models

Additional access:

- Create, edit, and delete connections
- Create, edit, and delete event rules and consumer rules
- Retry failed/dead events
- Access to RabbitMQ settings

## Access Control Matrix

| Model | User | Manager |
|-------|------|---------|
| `rabbitmq.connection` | Read | Full |
| `rabbitmq.event.rule` | Read | Full |
| `rabbitmq.consumer.rule` | Read | Full |
| `rabbitmq.event.log` | Read | Full |

## Menu Visibility

| Menu Item | Required Group |
|-----------|---------------|
| RabbitMQ (root menu) | User |
| Dashboard | User |
| Monitoring > Event Log | User |
| Configuration > Connections | Manager |
| Configuration > Event Rules | Manager |
| Configuration > Consumer Rules | Manager |
| Configuration > Settings | Manager |

## Best Practices

!!! tip "Principle of least privilege"
    Only grant Manager access to users who need to configure connections and rules. Most users only need the User group for monitoring.

- **Connections contain credentials.** Restrict Manager access to trusted administrators.
- **Consumer rules execute code.** The `target_method` field determines which method is called — only Managers should be able to set this.
- **Event rules control data flow.** Misconfigured rules can flood RabbitMQ or miss critical events.
