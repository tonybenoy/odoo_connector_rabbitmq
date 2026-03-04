# Production Deployment

## RabbitMQ Setup

### Dedicated credentials

Never use the default `guest` account in production. Create a dedicated user:

```bash
rabbitmqctl add_user odoo_app strong_password_here
rabbitmqctl set_permissions -p / odoo_app ".*" ".*" ".*"
```

Update the Odoo connection accordingly.

### Virtual hosts

Use a dedicated virtual host to isolate Odoo traffic:

```bash
rabbitmqctl add_vhost odoo
rabbitmqctl set_permissions -p odoo odoo_app ".*" ".*" ".*"
```

## SSL/TLS

### Enable SSL on the connection

1. Go to **RabbitMQ > Configuration > Connections**
2. Enable **SSL/TLS**
3. Upload the **CA Certificate** if using a private CA
4. Set the port to `5671` (standard AMQPS port)

### Using a connection URI

For managed services, use the full AMQPS URI:

```
amqps://user:password@rabbitmq.example.com:5671/odoo
```

### RabbitMQ server SSL configuration

Add to `rabbitmq.conf`:

```ini
listeners.ssl.default = 5671
ssl_options.cacertfile = /path/to/ca_certificate.pem
ssl_options.certfile = /path/to/server_certificate.pem
ssl_options.keyfile = /path/to/server_key.pem
ssl_options.verify = verify_peer
ssl_options.fail_if_no_peer_cert = false
```

## Clustering

For high availability, run a RabbitMQ cluster with mirrored queues:

### Connection URI with multiple nodes

```
amqp://user:pass@node1:5672,node2:5672,node3:5672/odoo
```

The module's connection pooling handles failover — if one node goes down, it reconnects to the next available node.

### Queue mirroring

Configure a policy to mirror queues across cluster nodes:

```bash
rabbitmqctl set_policy ha-odoo "^odoo" \
  '{"ha-mode":"all","ha-sync-mode":"automatic"}' \
  --apply-to queues
```

## Performance Tuning

### Odoo settings

| Setting | Recommendation | Why |
|---------|---------------|-----|
| Consumer Interval | `1` minute | Faster message processing |
| Max Retries | `5` | Balance between persistence and cleanup |
| Log Retention | `7-14` days | Reduce database growth |
| Prefetch Count | `10-50` | Match your processing capacity |

### RabbitMQ settings

| Setting | Recommendation |
|---------|---------------|
| `vm_memory_high_watermark` | `0.4` (40% of RAM) |
| `disk_free_limit` | `1GB` minimum |
| `heartbeat` | `60-600` seconds |
| `channel_max` | `2048` |

### Connection tuning

| Odoo Field | Production Value | Notes |
|------------|-----------------|-------|
| Heartbeat | `60` seconds | Detect dead connections faster |
| Connection Timeout | `30` seconds | Allow for network latency |

## Monitoring

### RabbitMQ metrics to watch

- **Queue depth** — messages waiting to be consumed. Growing queues indicate consumers can't keep up.
- **Message rates** — publish/consume rates. Watch for sudden drops.
- **Connection count** — each Odoo worker creates one connection. Monitor for leaks.
- **Memory usage** — RabbitMQ blocks publishers when memory is high.

### Odoo metrics to watch

- **Pending events** — `rabbitmq.event.log` records with `state = 'pending'`. A growing count means the outbound cron can't keep up.
- **Failed events** — events stuck in `failed` state. Investigate the error messages.
- **Dead events** — events that exhausted all retries. Require manual intervention.

### Health check query

```sql
SELECT state, COUNT(*)
FROM rabbitmq_event_log
WHERE direction = 'outbound'
  AND create_date > NOW() - INTERVAL '1 hour'
GROUP BY state;
```

## Backup and Recovery

The outbox pattern means events are stored in the Odoo database. Standard PostgreSQL backup procedures cover event data.

!!! tip
    After restoring a database backup, pending and failed events will be retried automatically by the cron jobs. Ensure RabbitMQ is accessible before starting Odoo to avoid a flood of failures.
