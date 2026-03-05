import json
import logging
import uuid

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Models that must never be intercepted (prevents recursion / internal noise)
_SKIP_MODELS = frozenset(
    {
        'rabbitmq.event.rule',
        'rabbitmq.event.log',
        'rabbitmq.consumer.rule',
        'rabbitmq.consumer.field.mapping',
        'rabbitmq.connection',
        'rabbitmq.service',
        'ir.config_parameter',
    }
)


# ---------------------------------------------------------------------------
# Rules cache
# ---------------------------------------------------------------------------
#
# The cache is stored on the registry as ``_rabbitmq_rules_cache``.
# Structure:  { model_name: { event_type: [rule_data, ...] } }
#
# Only models that have at least one active rule appear in the cache.
# At build time, models in _SKIP_MODELS, transient models, and models
# using the legacy mixin are filtered out — so the hot path never needs
# to call _should_skip().
#
# Hot path for a model with no rules (99.9% of calls):
#   cache = registry._rabbitmq_rules_cache   # direct attr (pre-initialized)
#   if cache is not None:                     # None = needs rebuild
#       model_name in cache                   # single dict 'in' check → False
# That's it: 1 attr access + 1 dict lookup.
# ---------------------------------------------------------------------------


def _build_rules_cache(env):
    """Query the DB, filter, and store the rules cache on the registry."""
    # If the global hook is disabled, return an empty cache — zero overhead
    icp = env['ir.config_parameter'].sudo()
    if icp.get_param('odoo_connector_rabbitmq.global_hook_enabled', 'True') != 'True':
        env.registry._rabbitmq_rules_cache = {}
        return {}

    rules = env['rabbitmq.event.rule'].sudo().search([('active', '=', True)])
    cache = {}
    for rule in rules:
        model_name = rule.model_name
        if not model_name:
            continue
        # Filter at build time — these checks never run on the hot path
        if model_name in _SKIP_MODELS:
            continue
        # Skip models using the legacy mixin
        model_obj = env.get(model_name)
        if model_obj is not None:
            if getattr(type(model_obj), '_transient', False):
                continue
            if hasattr(model_obj, '_rmq_get_rules'):
                continue

        event_type = rule.event_type
        cache.setdefault(model_name, {}).setdefault(event_type, []).append(
            {
                'id': rule.id,
                'exchange_name': rule.exchange_name,
                'exchange_type': rule.exchange_type,
                'routing_key': rule._get_routing_key(),
                'field_names': frozenset(rule.field_ids.mapped('name')) if rule.field_ids else frozenset(),
                'state_field': rule.state_field or 'state',
            }
        )
    env.registry._rabbitmq_rules_cache = cache
    return cache


def _invalidate_rules_cache(registry):
    """Mark the cache as stale so it is rebuilt on next ORM call."""
    registry._rabbitmq_rules_cache = None


# ---------------------------------------------------------------------------
# Payload / logging helpers
# ---------------------------------------------------------------------------


def _serialize_vals(vals):
    """Make vals JSON-serializable."""
    result = {}
    for key, value in vals.items():
        if isinstance(value, models.BaseModel):
            result[key] = value.ids
        else:
            try:
                json.dumps(value)
                result[key] = value
            except (TypeError, ValueError):
                result[key] = str(value)
    return result


def _prepare_payload(env, event_type, model_name, records, vals=None, old_vals=None):
    """Build standardized event payload."""
    payload = {
        'event_id': str(uuid.uuid4()),
        'timestamp': fields.Datetime.now().isoformat() + 'Z',
        'database': env.cr.dbname,
        'model': model_name,
        'event_type': event_type,
        'record_ids': records.ids,
        'user_id': env.uid,
        'user_login': env.user.login,
    }
    if vals is not None:
        payload['values'] = _serialize_vals(vals)
    if old_vals is not None:
        payload['old_values'] = _serialize_vals(old_vals)
        if vals:
            payload['changed_fields'] = list(vals.keys())
    return payload


def _log_event(env, rule_data, payload):
    """Create an outbound event log entry from a rule_data dict."""
    event_id = payload.get('event_id', str(uuid.uuid4()))
    max_retries = int(
        env['ir.config_parameter']
        .sudo()
        .get_param(
            'odoo_connector_rabbitmq.max_retries',
            '5',
        )
    )
    env['rabbitmq.event.log'].sudo().create(
        {
            'event_id': event_id,
            'direction': 'outbound',
            'model_name': payload.get('model', ''),
            'event_type': payload.get('event_type', ''),
            'record_ids': json.dumps(payload.get('record_ids', [])),
            'payload': json.dumps(payload, default=str),
            'exchange_name': rule_data['exchange_name'],
            'routing_key': rule_data['routing_key'],
            'state': 'pending',
            'max_retries': max_retries,
        }
    )


# ---------------------------------------------------------------------------
# Event firing (only called when rules exist — off the hot path)
# ---------------------------------------------------------------------------


def _fire_create_events(self, records, vals_list, create_rules):
    """Fire create event rules. Called only when rules exist."""
    vals = vals_list[0] if len(vals_list) == 1 else {}
    for rule_data in create_rules:
        payload = _prepare_payload(
            self.env,
            'create',
            self._name,
            records,
            vals=vals,
        )
        _log_event(self.env, rule_data, payload)


def _fire_write_events(self, vals, old_values, rules_write, rules_state):
    """Fire write and state_change event rules. Called only when rules exist."""
    # Fire write rules
    vals_keys = vals.keys()
    for rd in rules_write:
        if rd['field_names'] and rd['field_names'].isdisjoint(vals_keys):
            continue
        payload = _prepare_payload(
            self.env,
            'write',
            self._name,
            self,
            vals=vals,
            old_vals=old_values.get(self[:1].id, {}),
        )
        _log_event(self.env, rd, payload)

    # Fire state_change rules
    for rd in rules_state:
        sf = rd.get('state_field', 'state')
        if sf not in vals:
            continue
        for record in self:
            old_state = old_values.get(record.id, {}).get(sf)
            new_state = vals[sf]
            if old_state != new_state:
                payload = _prepare_payload(
                    self.env,
                    'state_change',
                    self._name,
                    record,
                    vals={sf: new_state},
                    old_vals={sf: old_state},
                )
                payload['state_transition'] = {
                    'field': sf,
                    'from': old_state,
                    'to': new_state,
                }
                _log_event(self.env, rd, payload)


def _fire_unlink_events(self, snapshot, unlink_rules):
    """Fire unlink event rules. Called only when rules exist."""
    for rd in unlink_rules:
        payload = _prepare_payload(
            self.env,
            'unlink',
            self._name,
            self,
        )
        payload['deleted_records'] = snapshot
        _log_event(self.env, rd, payload)


# ---------------------------------------------------------------------------
# Patched ORM methods — hot path is inlined for maximum performance
# ---------------------------------------------------------------------------


def _patched_create(original_create):
    """Return a patched create that fires event rules."""

    @api.model_create_multi
    def create(self, vals_list):
        records = original_create(self, vals_list)
        # --- HOT PATH: 1 attr access + 1 dict lookup for no-rules models ---
        cache = getattr(self.env.registry, '_rabbitmq_rules_cache', None)
        if cache is None:
            try:
                cache = _build_rules_cache(self.env)
            except Exception:
                return records
        model_cache = cache.get(self._name)
        if model_cache is None:
            return records
        # --- END HOT PATH — below only runs for models with rules ---
        create_rules = model_cache.get('create')
        if create_rules:
            try:
                _fire_create_events(self, records, vals_list, create_rules)
            except Exception:
                _logger.exception('RabbitMQ global hook error in create for %s', self._name)
        return records

    return create


def _patched_write(original_write):
    """Return a patched write that fires event rules."""

    def write(self, vals):
        # --- HOT PATH: 1 attr access + 1 dict lookup for no-rules models ---
        cache = getattr(self.env.registry, '_rabbitmq_rules_cache', None)
        if cache is None:
            try:
                cache = _build_rules_cache(self.env)
            except Exception:
                return original_write(self, vals)
        model_cache = cache.get(self._name)
        if model_cache is None:
            return original_write(self, vals)
        # --- END HOT PATH ---

        rules_write = model_cache.get('write', [])
        rules_state = model_cache.get('state_change', [])
        if not rules_write and not rules_state:
            return original_write(self, vals)

        # Snapshot old values before write
        old_values = {}
        try:
            # field_names are pre-computed frozensets — union is cheap
            tracked_fields = frozenset().union(*(rd['field_names'] for rd in rules_write))
            state_fields = frozenset(rd['state_field'] for rd in rules_state)
            snapshot_fields = tracked_fields | state_fields | vals.keys()
            for record in self:
                record_vals = {}
                for fname in snapshot_fields:
                    if fname in self._fields:
                        value = record[fname]
                        if isinstance(value, models.BaseModel):
                            record_vals[fname] = value.ids
                        else:
                            record_vals[fname] = value
                old_values[record.id] = record_vals
        except Exception:
            _logger.exception('RabbitMQ global hook error snapshotting for %s', self._name)

        result = original_write(self, vals)

        try:
            _fire_write_events(self, vals, old_values, rules_write, rules_state)
        except Exception:
            _logger.exception('RabbitMQ global hook error in write for %s', self._name)

        return result

    return write


def _patched_unlink(original_unlink):
    """Return a patched unlink that fires event rules."""

    def unlink(self):
        # --- HOT PATH: 1 attr access + 1 dict lookup for no-rules models ---
        cache = getattr(self.env.registry, '_rabbitmq_rules_cache', None)
        if cache is None:
            try:
                cache = _build_rules_cache(self.env)
            except Exception:
                return original_unlink(self)
        model_cache = cache.get(self._name)
        if model_cache is None:
            return original_unlink(self)
        # --- END HOT PATH ---

        unlink_rules = model_cache.get('unlink', [])
        snapshot = []
        if unlink_rules:
            try:
                for record in self:
                    snapshot.append(
                        {
                            'id': record.id,
                            'display_name': record.display_name,
                        }
                    )
            except Exception:
                _logger.exception('RabbitMQ global hook error snapshotting unlink for %s', self._name)

        result = original_unlink(self)

        if unlink_rules:
            try:
                _fire_unlink_events(self, snapshot, unlink_rules)
            except Exception:
                _logger.exception('RabbitMQ global hook error in unlink for %s', self._name)

        return result

    return unlink


# ---------------------------------------------------------------------------
# post_load entry point
# ---------------------------------------------------------------------------


def post_load():
    """Patch BaseModel ORM methods at module load time.

    Called by Odoo via the ``post_load`` manifest key.
    """
    BaseModel = models.BaseModel

    # Save originals
    _original_create = BaseModel.create
    _original_write = BaseModel.write
    _original_unlink = BaseModel.unlink

    # Apply patches
    BaseModel.create = _patched_create(_original_create)
    BaseModel.write = _patched_write(_original_write)
    BaseModel.unlink = _patched_unlink(_original_unlink)

    _logger.info('RabbitMQ global event hook installed on BaseModel')
