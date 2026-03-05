import json
import logging
import uuid

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class RabbitMQEventBusMixin(models.AbstractModel):
    _name = 'rabbitmq.event.bus.mixin'
    _description = 'RabbitMQ Event Bus Mixin'

    def _rmq_get_rules(self, event_type):
        """Get active event rules for this model and event type."""
        return (
            self.env['rabbitmq.event.rule']
            .sudo()
            .search(
                [
                    ('model_name', '=', self._name),
                    ('event_type', '=', event_type),
                    ('active', '=', True),
                ]
            )
        )

    def _rmq_prepare_payload(self, event_type, records, vals=None, old_vals=None):
        """Build the standardized event payload."""
        payload = {
            'event_id': str(uuid.uuid4()),
            'timestamp': fields.Datetime.now().isoformat() + 'Z',
            'database': self.env.cr.dbname,
            'model': self._name,
            'event_type': event_type,
            'record_ids': records.ids,
            'user_id': self.env.uid,
            'user_login': self.env.user.login,
        }
        if vals is not None:
            payload['values'] = self._rmq_serialize_vals(vals)
        if old_vals is not None:
            payload['old_values'] = self._rmq_serialize_vals(old_vals)
            if vals:
                payload['changed_fields'] = list(vals.keys())
        return payload

    def _rmq_serialize_vals(self, vals):
        """Make vals JSON-serializable (handle dates, recordsets, etc.)."""
        result = {}
        for key, value in vals.items():
            if isinstance(value, models.BaseModel):
                result[key] = value.ids
            elif isinstance(value, (fields.Date, fields.Datetime)):
                result[key] = str(value)
            else:
                try:
                    json.dumps(value)
                    result[key] = value
                except (TypeError, ValueError):
                    result[key] = str(value)
        return result

    def _rmq_log_event(self, rule, payload):
        """Create an outbound event log entry."""
        event_id = payload.get('event_id', str(uuid.uuid4()))
        self.env['rabbitmq.event.log'].sudo().create(
            {
                'event_id': event_id,
                'direction': 'outbound',
                'model_name': self._name,
                'event_type': payload.get('event_type', ''),
                'record_ids': json.dumps(payload.get('record_ids', [])),
                'payload': json.dumps(payload, default=str),
                'exchange_name': rule.exchange_name,
                'routing_key': rule._get_routing_key(),
                'state': 'pending',
                'max_retries': int(
                    self.env['ir.config_parameter']
                    .sudo()
                    .get_param(
                        'odoo_connector_rabbitmq.max_retries',
                        '5',
                    )
                ),
            }
        )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        rules = self._rmq_get_rules('create')
        if rules:
            for rule in rules:
                payload = self._rmq_prepare_payload('create', records, vals=vals_list[0] if len(vals_list) == 1 else {})
                self._rmq_log_event(rule, payload)
        return records

    def write(self, vals):
        # Snapshot old values for tracked fields and state changes
        old_values = {}
        rules_write = self._rmq_get_rules('write')
        rules_state = self._rmq_get_rules('state_change')

        tracked_fields = set()
        for rule in rules_write:
            if rule.field_ids:
                tracked_fields.update(rule.field_ids.mapped('name'))

        state_fields = set()
        for rule in rules_state:
            if rule.state_field:
                state_fields.add(rule.state_field)

        snapshot_fields = tracked_fields | state_fields | set(vals.keys())
        if rules_write or rules_state:
            for record in self:
                record_vals = {}
                for field_name in snapshot_fields:
                    if field_name in self._fields:
                        value = record[field_name]
                        if isinstance(value, models.BaseModel):
                            record_vals[field_name] = value.ids
                        else:
                            record_vals[field_name] = value
                old_values[record.id] = record_vals

        result = super().write(vals)

        # Check write rules
        for rule in rules_write:
            if rule.field_ids:
                rule_field_names = set(rule.field_ids.mapped('name'))
                if not (set(vals.keys()) & rule_field_names):
                    continue
            payload = self._rmq_prepare_payload(
                'write',
                self,
                vals=vals,
                old_vals=old_values.get(self[:1].id, {}),
            )
            self._rmq_log_event(rule, payload)

        # Check state_change rules
        for rule in rules_state:
            sf = rule.state_field or 'state'
            if sf not in vals:
                continue
            for record in self:
                old_state = old_values.get(record.id, {}).get(sf)
                new_state = vals[sf]
                if old_state != new_state:
                    payload = self._rmq_prepare_payload(
                        'state_change',
                        record,
                        vals={sf: new_state},
                        old_vals={sf: old_state},
                    )
                    payload['state_transition'] = {
                        'field': sf,
                        'from': old_state,
                        'to': new_state,
                    }
                    self._rmq_log_event(rule, payload)

        return result

    def unlink(self):
        rules = self._rmq_get_rules('unlink')
        if rules:
            # Snapshot before deletion
            snapshot = []
            for record in self:
                snapshot.append(
                    {
                        'id': record.id,
                        'display_name': record.display_name,
                    }
                )
            for rule in rules:
                payload = self._rmq_prepare_payload('unlink', self)
                payload['deleted_records'] = snapshot
                self._rmq_log_event(rule, payload)

        return super().unlink()
