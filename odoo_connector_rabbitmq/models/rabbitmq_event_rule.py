from odoo import api, fields, models


class RabbitMQEventRule(models.Model):
    _name = 'rabbitmq.event.rule'
    _description = 'RabbitMQ Event Rule'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    model_id = fields.Many2one(
        'ir.model',
        string='Model',
        required=True,
        ondelete='cascade',
        help='Odoo model to watch for events.',
    )
    model_name = fields.Char(
        related='model_id.model',
        string='Model Name',
        store=True,
        readonly=True,
    )
    event_type = fields.Selection(
        [
            ('create', 'Create'),
            ('write', 'Write'),
            ('unlink', 'Unlink'),
            ('state_change', 'State Change'),
            ('custom', 'Custom'),
        ],
        string='Event Type',
        required=True,
        default='create',
    )
    exchange_name = fields.Char(
        string='Exchange',
        required=True,
        default='odoo_events',
    )
    exchange_type = fields.Selection(
        [('direct', 'Direct'), ('topic', 'Topic'), ('fanout', 'Fanout')],
        string='Exchange Type',
        default='topic',
    )
    routing_key = fields.Char(
        string='Routing Key',
        help='Supports placeholders: {model}, {event}. Example: odoo.{model}.{event}',
    )
    field_ids = fields.Many2many(
        'ir.model.fields',
        string='Tracked Fields',
        help='Only trigger on changes to these fields (for write events). Leave empty to trigger on any field change.',
    )
    state_field = fields.Char(
        string='State Field',
        default='state',
        help='Field name to watch for state transitions (for state_change events).',
    )
    active = fields.Boolean(string='Active', default=True)

    def _get_routing_key(self):
        """Resolve routing key placeholders."""
        self.ensure_one()
        key = self.routing_key or ''
        return key.replace('{model}', self.model_name or '').replace(
            '{event}',
            self.event_type or '',
        )

    def _invalidate_rules_cache(self):
        """Invalidate the global rules cache after any rule change."""
        from ..hooks import _invalidate_rules_cache

        _invalidate_rules_cache(self.env.registry)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._invalidate_rules_cache()
        return records

    def write(self, vals):
        result = super().write(vals)
        self._invalidate_rules_cache()
        return result

    def unlink(self):
        registry = self.env.registry
        result = super().unlink()
        from ..hooks import _invalidate_rules_cache

        _invalidate_rules_cache(registry)
        return result
