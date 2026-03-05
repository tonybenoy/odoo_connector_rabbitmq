# CLAUDE.md — Odoo Connector RabbitMQ

## Project Overview

Odoo module (17, 18, 19) for bidirectional RabbitMQ integration using a **zero-code** approach.
Publishing and consuming are configured entirely via Odoo UI — no Python code needed.

## Architecture

- **Global Hook** (`hooks.py`): Patches `BaseModel.create/write/unlink` via `post_load` manifest key. Uses an in-memory rules cache on the registry (`registry._rabbitmq_rules_cache`).
- **Transactional Outbox** (`rabbitmq.event.log`): Events are written to DB atomically with business data, then published asynchronously by cron.
- **Consumer Rules** (`rabbitmq.consumer.rule`): Two modes — Field Mapping (zero-code) and Call Method (legacy).
- **Legacy Mixin** (`rabbitmq.event.bus.mixin`): Kept for backward compat; models using it are auto-skipped by the global hook.

## Key Files

| File | Purpose |
|------|---------|
| `hooks.py` | Global BaseModel patch, rules cache, event firing |
| `decorator.py` | `@rabbitmq_event` decorator for custom method events |
| `models/rabbitmq_service.py` | Connection pooling, publish/consume, ack/nack |
| `models/rabbitmq_event_log.py` | Outbox table, cron jobs (publish, consume, retry, cleanup) |
| `models/rabbitmq_event_rule.py` | Event rule config, cache invalidation on CRUD |
| `models/rabbitmq_consumer_rule.py` | Consumer config, field mapping processor, validation |
| `models/rabbitmq_consumer_field_mapping.py` | JSON-to-Odoo field mapping definitions |
| `models/rabbitmq_connection.py` | Connection config, SSL, test button |
| `models/res_config_settings.py` | System settings (toggles, tuning params) |

## Commands

```bash
# Lint
ruff check odoo_connector_rabbitmq/

# Run Odoo tests (requires running Odoo instance)
docker compose exec web odoo -d test_rabbitmq -u odoo_connector_rabbitmq --test-enable --stop-after-init

# Start dev stack
docker compose up -d
```

## Conventions

- **Python 3.10+**, strict ruff linting (see `pyproject.toml`)
- **MIT License**
- Module version format: `{odoo_version}.x.y.z` (e.g. `19.0.1.0.0`)
- All event bus errors are caught silently — never break normal ORM operations
- Registry attributes use `getattr(..., None)` pattern (not direct access)
- Rules cache is invalidated on event rule CRUD and settings save
- Models in `_SKIP_MODELS` (hooks.py) are never intercepted
- Raw SQL uses `FOR UPDATE SKIP LOCKED` for multi-worker safety

## Testing

Tests are in `odoo_connector_rabbitmq/tests/`. They use Odoo's `TransactionCase`.
Docker stack: `docker-compose.yml` (Odoo + PostgreSQL 16 + RabbitMQ 3).
Test stacks: `docker-compose.test-18.yml`, `docker-compose.test-19.yml`.

## Version-Specific Notes

- **Odoo 17**: Uses `tree` view type, `category_id` on groups, `users` field
- **Odoo 18**: Uses `list` view type, `category_id` on groups, `users` field
- **Odoo 19**: Uses `list` view type, `privilege_id` via `res.groups.privilege`, `user_ids` field
- Main branch tracks Odoo 19; version branches `17.0` and `18.0` have adapted XML
