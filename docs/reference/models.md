# Models Reference

## rabbitmq.connection

Manages RabbitMQ connection configurations.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | Char | *required* | Connection name |
| `connection_uri` | Char | | Full AMQP URI (overrides individual fields) |
| `host` | Char | `localhost` | RabbitMQ host |
| `port` | Integer | `5672` | AMQP port |
| `username` | Char | `guest` | Authentication username |
| `password` | Char | `guest` | Authentication password |
| `virtual_host` | Char | `/` | RabbitMQ virtual host |
| `ssl_enabled` | Boolean | `False` | Enable SSL/TLS |
| `ssl_ca_cert` | Binary | | CA certificate for SSL |
| `heartbeat` | Integer | `600` | Heartbeat interval (seconds) |
| `connection_timeout` | Integer | `10` | Connection timeout (seconds) |
| `active` | Boolean | `True` | Active flag |
| `state` | Selection | `disconnected` | `disconnected`, `connected`, `error` (readonly) |
| `last_error` | Text | | Last connection error (readonly) |

### Methods

#### `_get_connection_params()`

Returns `pika.ConnectionParameters` built from the connection configuration. Supports URI, SSL, and individual field modes.

#### `action_test_connection()`

Tests the RabbitMQ connection and displays a notification with the result.

---

## rabbitmq.service

Abstract service layer for RabbitMQ operations. Not stored in the database.

### Methods

#### `_get_default_connection()`

Returns the default `rabbitmq.connection` record from system settings. Falls back to the first active connection.

#### `_get_connection()`

Returns a cached `pika.BlockingConnection`. Creates a new one if none exists or the existing one is closed. Connections are cached at the Odoo registry level.

#### `_get_channel()`

Returns a channel with publisher confirms enabled. Reconnects automatically on channel/connection failure.

#### `_close_connection()`

Gracefully closes the cached connection.

#### `_ensure_exchange(channel, name, exchange_type='direct')`

Declares an exchange idempotently (passive=False, durable=True).

#### `_ensure_queue(channel, queue_name, exchange_name=None, routing_key=None)`

Declares a durable queue and optionally binds it to an exchange.

#### `_publish(exchange, routing_key, body, content_type='application/json')`

Publishes a message with publisher confirms. Raises on delivery failure.

#### `_consume_batch(queue_name, exchange_name=None, routing_key=None, prefetch_count=10)`

Consumes up to `prefetch_count` messages from a queue. Returns a list of `(channel, method, properties, body)` tuples.

#### `_ack_message(channel, delivery_tag)`

Acknowledges a message.

#### `_nack_message(channel, delivery_tag, requeue=True)`

Negative-acknowledges a message with optional requeue.

---

## rabbitmq.event.rule

Defines rules for automatic event emission on model lifecycle events. Changes to event rules automatically invalidate the global rules cache — new rules take effect immediately without a restart.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | Char | *required* | Rule name |
| `model_id` | Many2one -> `ir.model` | *required* | Model to watch |
| `model_name` | Char | | Technical model name (related, readonly) |
| `on_create` | Boolean | `True` | Emit event on record creation |
| `on_write` | Boolean | `False` | Emit event on record update |
| `on_unlink` | Boolean | `False` | Emit event on record deletion |
| `on_state_change` | Boolean | `False` | Emit event on state field transition |
| `event_type` | Selection | | Legacy field (hidden). Kept for backward compatibility |
| `exchange_name` | Char | `odoo_events` | Target exchange |
| `exchange_type` | Selection | `topic` | `direct`, `topic`, `fanout` |
| `routing_key` | Char | | Supports `{model}` and `{event}` placeholders |
| `field_ids` | Many2many -> `ir.model.fields` | | Tracked fields (write events only) |
| `state_field` | Char | `state` | Field to watch for state transitions |
| `active` | Boolean | `True` | Active flag |
| `event_count` | Integer | | Number of related event log entries (computed) |

A single rule can track multiple operations. For example, enabling On Create + On Update + On Delete captures all CRUD events for a model in one rule.

### Methods

#### `_get_routing_key(event_type=None)`

Resolves routing key placeholders (`{model}`, `{event}`) to actual values. When a rule tracks multiple event types, the `{event}` placeholder resolves per event type.

#### `_get_enabled_event_types()`

Returns a list of event type strings enabled via the CRUD checkboxes. Falls back to the legacy `event_type` field if no checkboxes are set.

---

## rabbitmq.consumer.rule

Defines rules for consuming messages from RabbitMQ. Supports two processing modes: **Call Method** (legacy) and **Field Mapping** (zero-code).

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | Char | *required* | Rule name |
| `queue_name` | Char | *required* | Queue to consume from |
| `exchange_name` | Char | | Exchange name |
| `routing_key` | Char | | Binding key |
| `target_model` | Char | *required* | Target Odoo model (e.g., `res.partner`) |
| `processing_mode` | Selection | `method` | `method` (Call Method) or `mapping` (Field Mapping) |
| `target_method` | Char | | Method to invoke (for Call Method mode) |
| `consumer_action` | Selection | `create` | `create`, `write`, `upsert`, `unlink` (for Field Mapping mode) |
| `match_field` | Char | | Odoo field to match existing records (for write/upsert/unlink) |
| `payload_root` | Char | | Dot-notation path to data in JSON payload |
| `mapping_ids` | One2many | | Field mappings (for Field Mapping mode) |
| `prefetch_count` | Integer | `10` | Max messages per batch |
| `auto_ack` | Boolean | `False` | Auto-acknowledge after processing |
| `active` | Boolean | `True` | Active flag |

### Constraints

- **Target model must exist** — validated on save
- **Target method must exist on model** — validated on save (Call Method mode)
- **Action required** for mapping mode
- **Match field required** for update/upsert/delete actions
- **Delete action must be enabled** in Settings > RabbitMQ > Consumer Safety

### Methods

#### `_process_message_mapping(body_str)`

Processes an inbound message using field mappings. Parses JSON, navigates to payload root, converts values per mapping, and performs the configured action (create/write/upsert/unlink).

---

## rabbitmq.consumer.field.mapping

Defines how JSON message fields map to Odoo model fields. Used by consumer rules in Field Mapping mode.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `consumer_rule_id` | Many2one -> `rabbitmq.consumer.rule` | *required* | Parent consumer rule |
| `sequence` | Integer | `10` | Display order |
| `source_field` | Char | *required* | JSON key (dot notation supported, e.g. `address.city`) |
| `target_field` | Char | *required* | Odoo field name |
| `field_type` | Selection | `char` | `char`, `integer`, `float`, `boolean`, `date`, `datetime`, `many2one_id`, `many2one_search`, `raw` |
| `search_model` | Char | | Model for many2one_search lookups (e.g. `res.country`) |
| `search_field` | Char | | Field for many2one_search lookups (e.g. `code`) |
| `default_value` | Char | | Fallback value if source is missing |

---

## rabbitmq.event.log

Transactional outbox — stores pending, sent, failed, and dead events.

### Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `event_id` | Char | | UUID (readonly, indexed) |
| `direction` | Selection | *required* | `outbound`, `inbound` (readonly, indexed) |
| `model_name` | Char | | Source/target model (readonly, indexed) |
| `event_type` | Char | | Event type (readonly, indexed) |
| `record_ids` | Text | | JSON array of record IDs (readonly) |
| `payload` | Text | | Full JSON payload (readonly) |
| `exchange_name` | Char | | Exchange used (readonly) |
| `routing_key` | Char | | Routing key used (readonly) |
| `queue_name` | Char | | Queue consumed from (readonly) |
| `state` | Selection | `pending` | `pending`, `sent`, `received`, `failed`, `dead` (readonly, indexed) |
| `error_message` | Text | | Error details (readonly) |
| `retry_count` | Integer | `0` | Current retry attempt (readonly) |
| `max_retries` | Integer | `5` | Max retries before dead-lettering (readonly) |
| `next_retry_at` | Datetime | | Next retry time (readonly) |

### Methods

#### `action_retry()`

Resets a single failed or dead event to `pending` state.

#### `action_retry_all_dead()`

Resets all dead events to `pending` state.

#### `_process_pending_outbound()`

Cron method. Publishes pending outbound events to RabbitMQ with retry logic.

#### `_process_inbound()`

Cron method. Consumes messages from all active consumer rules. Dispatches to field mapping processor or target method based on the rule's processing mode.

#### `_retry_failed_events()`

Cron method. Resets failed events past their backoff time to `pending`.

#### `_cleanup_old_logs()`

Cron method. Deletes sent/received logs older than the configured retention period.

---

## rabbitmq.event.bus.mixin (Legacy)

!!! note
    This mixin is kept for backward compatibility. New integrations should use the global hook instead (just create Event Rules in the UI — no code needed). Models using the mixin are automatically skipped by the global hook to prevent double-firing.

Abstract mixin for automatic event capture on model lifecycle.

### Methods

#### `_rmq_get_rules(event_type)`

Returns active event rules for the current model and event type.

#### `_rmq_prepare_payload(event_type, records, vals=None, old_vals=None)`

Builds a standardized event payload dictionary.

#### `_rmq_serialize_vals(vals)`

Converts field values to JSON-serializable format.

#### `_rmq_log_event(rule, payload)`

Creates an outbound `rabbitmq.event.log` entry.

### Overridden Methods

- **`create(vals_list)`** — emits `create` events
- **`write(vals)`** — emits `write` and `state_change` events with old values
- **`unlink()`** — emits `unlink` events with a snapshot of deleted records
