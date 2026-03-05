import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class RabbitMQConsumerRule(models.Model):
    _name = 'rabbitmq.consumer.rule'
    _description = 'RabbitMQ Consumer Rule'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    queue_name = fields.Char(string='Queue', required=True)
    exchange_name = fields.Char(string='Exchange')
    routing_key = fields.Char(string='Binding Key')
    target_model = fields.Char(
        string='Target Model',
        required=True,
        help='Odoo model technical name (e.g. res.partner).',
    )
    processing_mode = fields.Selection(
        [('method', 'Call Method'), ('mapping', 'Field Mapping')],
        string='Processing Mode',
        default='method',
        required=True,
    )
    target_method = fields.Char(
        string='Target Method',
        help='Method to invoke on the target model. Method receives (body, properties) as arguments.',
    )
    consumer_action = fields.Selection(
        [('create', 'Create'), ('write', 'Update'), ('upsert', 'Create or Update'), ('unlink', 'Delete')],
        string='Action',
        default='create',
        help='Action to perform on matched records in mapping mode.',
    )
    match_field = fields.Char(
        string='Match Field',
        help='Odoo field to match existing records for write/upsert/unlink '
        '(e.g. "email"). The source value comes from the mapping '
        'with this target field.',
    )
    payload_root = fields.Char(
        string='Payload Root',
        help='Dot-notation path to the data in the JSON payload '
        '(e.g. "data.partner"). Leave empty to use the root object.',
    )
    mapping_ids = fields.One2many(
        'rabbitmq.consumer.field.mapping',
        'consumer_rule_id',
        string='Field Mappings',
    )
    prefetch_count = fields.Integer(
        string='Messages per Batch',
        default=10,
        help='Maximum number of messages to process per cron cycle.',
    )
    auto_ack = fields.Boolean(
        string='Auto Acknowledge',
        default=False,
        help='Automatically acknowledge messages after processing.',
    )
    active = fields.Boolean(string='Active', default=True)

    # ------------------------------------------------------------------
    # Constraints
    # ------------------------------------------------------------------

    @api.constrains('target_model')
    def _check_target_model(self):
        for rule in self:
            if rule.target_model and self.env.get(rule.target_model) is None:
                raise ValidationError(_("Target model '%(model)s' does not exist.", model=rule.target_model))

    @api.constrains('processing_mode', 'target_method')
    def _check_target_method(self):
        for rule in self:
            if rule.processing_mode == 'method' and not rule.target_method:
                raise ValidationError(_('Target Method is required when processing mode is Call Method.'))
            if rule.processing_mode == 'method' and rule.target_method and rule.target_model:
                model_obj = self.env.get(rule.target_model)
                if model_obj is not None and not hasattr(model_obj, rule.target_method):
                    raise ValidationError(
                        _(
                            "Method '%(method)s' not found on model '%(model)s'.",
                            method=rule.target_method,
                            model=rule.target_model,
                        )
                    )

    @api.constrains('processing_mode', 'consumer_action', 'match_field')
    def _check_mapping_config(self):
        for rule in self:
            if rule.processing_mode != 'mapping':
                continue
            if not rule.consumer_action:
                raise ValidationError(_('Action is required when processing mode is Field Mapping.'))
            if rule.consumer_action in ('write', 'upsert', 'unlink') and not rule.match_field:
                raise ValidationError(_('Match Field is required for Update, Create or Update, and Delete actions.'))

    @api.constrains('consumer_action')
    def _check_consumer_action_allowed(self):
        """Check if the consumer action is allowed by system settings."""
        icp = self.env['ir.config_parameter'].sudo()
        allow_delete = icp.get_param('odoo_connector_rabbitmq.consumer_allow_delete', 'False')
        for rule in self:
            if rule.consumer_action == 'unlink' and allow_delete != 'True':
                raise ValidationError(
                    _(
                        'Delete action is disabled. Enable it in Settings > RabbitMQ > '
                        'Consumer Safety > Allow Delete via Field Mapping.'
                    )
                )

    @api.onchange('processing_mode')
    def _onchange_processing_mode(self):
        if self.processing_mode == 'mapping':
            self.target_method = False
        else:
            self.consumer_action = False
            self.match_field = False
            self.payload_root = False

    # ------------------------------------------------------------------
    # Field Mapping processor
    # ------------------------------------------------------------------

    def _get_nested_value(self, data, dotted_key):
        """Retrieve a value from nested dicts using dot notation."""
        keys = dotted_key.split('.')
        for key in keys:
            if isinstance(data, dict):
                data = data.get(key)
            else:
                return None
        return data

    def _convert_mapping_value(self, mapping, raw_value):
        """Convert a raw JSON value according to the mapping's field_type."""
        if raw_value is None:
            # Use default if available
            raw_value = mapping.default_value
            if raw_value is None:
                return None

        ft = mapping.field_type
        if ft == 'raw':
            return raw_value
        if ft == 'char':
            return str(raw_value) if raw_value is not None else None
        if ft == 'integer':
            try:
                return int(raw_value)
            except (ValueError, TypeError):
                return None
        if ft == 'float':
            try:
                return float(raw_value)
            except (ValueError, TypeError):
                return None
        if ft == 'boolean':
            if isinstance(raw_value, bool):
                return raw_value
            if isinstance(raw_value, str):
                return raw_value.lower() in ('true', '1', 'yes')
            return bool(raw_value)
        if ft == 'date':
            # Expect ISO format string
            return str(raw_value)[:10] if raw_value else None
        if ft == 'datetime':
            return str(raw_value)[:19].replace('T', ' ') if raw_value else None
        if ft == 'many2one_id':
            try:
                return int(raw_value)
            except (ValueError, TypeError):
                return None
        if ft == 'many2one_search':
            if not mapping.search_model or not mapping.search_field:
                _logger.warning(
                    'Mapping %s: many2one_search requires search_model and search_field',
                    mapping.id,
                )
                return None
            search_model = self.env.get(mapping.search_model)
            if search_model is None:
                return None
            rec = search_model.sudo().search(
                [(mapping.search_field, '=', raw_value)],
                limit=1,
            )
            return rec.id if rec else None
        return raw_value

    def _process_message_mapping(self, body_str):
        """Process an inbound message using field mappings.

        Returns the created/updated recordset or True for unlink.
        """
        self.ensure_one()
        data = json.loads(body_str) if isinstance(body_str, str) else body_str

        # Navigate to payload root if specified
        if self.payload_root:
            data = self._get_nested_value(data, self.payload_root)
            if data is None:
                raise ValueError(f"Payload root '{self.payload_root}' not found in message")

        # Build vals dict from mappings
        vals = {}
        for mapping in self.mapping_ids:
            raw_value = self._get_nested_value(data, mapping.source_field)
            converted = self._convert_mapping_value(mapping, raw_value)
            if converted is not None:
                vals[mapping.target_field] = converted

        target_model = self.env[self.target_model].sudo()
        action = self.consumer_action or 'create'

        if action == 'create':
            return target_model.create(vals)

        if action in ('write', 'upsert', 'unlink'):
            if not self.match_field:
                raise ValueError(f'Match field is required for {action} action')
            match_value = vals.pop(self.match_field, None)
            if match_value is None:
                # Try to get from data directly
                for mapping in self.mapping_ids:
                    if mapping.target_field == self.match_field:
                        match_value = self._get_nested_value(
                            data,
                            mapping.source_field,
                        )
                        break
            if match_value is None:
                raise ValueError(f"No value found for match field '{self.match_field}'")

            existing = target_model.search(
                [(self.match_field, '=', match_value)],
                limit=1,
            )

            if action == 'write':
                if not existing:
                    raise ValueError(f'No record found matching {self.match_field}={match_value}')
                existing.write(vals)
                return existing

            if action == 'upsert':
                if existing:
                    existing.write(vals)
                    return existing
                else:
                    vals[self.match_field] = match_value
                    return target_model.create(vals)

            if action == 'unlink':
                if existing:
                    existing.unlink()
                return True

        raise ValueError(f'Unknown consumer action: {action}')
