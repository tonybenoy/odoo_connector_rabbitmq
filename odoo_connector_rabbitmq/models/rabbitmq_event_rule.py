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

    # --- CRUD checkboxes (preferred) ---
    on_create = fields.Boolean(
        string='On Create',
        default=True,
        help='Emit an event when a record is created.',
    )
    on_write = fields.Boolean(
        string='On Update',
        help='Emit an event when a record is updated.',
    )
    on_unlink = fields.Boolean(
        string='On Delete',
        help='Emit an event when a record is deleted.',
    )
    on_state_change = fields.Boolean(
        string='On State Change',
        help='Emit an event when the state field changes value.',
    )

    # --- Legacy event_type (kept for backward compat, hidden in UI) ---
    event_type = fields.Selection(
        [
            ('create', 'Create'),
            ('write', 'Write'),
            ('unlink', 'Unlink'),
            ('state_change', 'State Change'),
            ('custom', 'Custom'),
        ],
        string='Event Type (legacy)',
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

    # --- Computed counts ---
    event_count = fields.Integer(
        string='Events',
        compute='_compute_event_count',
    )

    def _compute_event_count(self):
        log_model = self.env['rabbitmq.event.log'].sudo()
        for rule in self:
            domain = [('direction', '=', 'outbound')]
            if rule.model_name:
                domain.append(('model_name', '=', rule.model_name))
            if rule.exchange_name:
                domain.append(('exchange_name', '=', rule.exchange_name))
            rule.event_count = log_model.search_count(domain)

    def action_view_events(self):
        self.ensure_one()
        domain = [('direction', '=', 'outbound')]
        if self.model_name:
            domain.append(('model_name', '=', self.model_name))
        if self.exchange_name:
            domain.append(('exchange_name', '=', self.exchange_name))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Event Logs',
            'res_model': 'rabbitmq.event.log',
            'view_mode': 'list,form',
            'domain': domain,
        }

    def _get_enabled_event_types(self):
        """Return list of enabled event types for this rule."""
        self.ensure_one()
        types = []
        if self.on_create:
            types.append('create')
        if self.on_write:
            types.append('write')
        if self.on_unlink:
            types.append('unlink')
        if self.on_state_change:
            types.append('state_change')
        # Legacy fallback: if no checkboxes set but event_type is, use it
        if not types and self.event_type:
            types.append(self.event_type)
        return types

    def _get_routing_key(self, event_type=None):
        """Resolve routing key placeholders."""
        self.ensure_one()
        key = self.routing_key or ''
        return key.replace('{model}', self.model_name or '').replace(
            '{event}',
            event_type or self.event_type or '',
        )

    def _invalidate_rules_cache(self):
        """Invalidate the global rules cache after any rule change."""
        from ..hooks import _invalidate_rules_cache

        _invalidate_rules_cache(self.env.registry)

    @api.model_create_multi
    def create(self, vals_list):
        # Migrate legacy event_type to checkboxes on create
        for vals in vals_list:
            if 'event_type' in vals and not any(
                k in vals for k in ('on_create', 'on_write', 'on_unlink', 'on_state_change')
            ):
                _migrate_event_type_to_booleans(vals)
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


def _migrate_event_type_to_booleans(vals):
    """Convert a legacy event_type value into boolean flags."""
    et = vals.get('event_type')
    if et == 'create':
        vals.setdefault('on_create', True)
    elif et == 'write':
        vals.setdefault('on_write', True)
    elif et == 'unlink':
        vals.setdefault('on_unlink', True)
    elif et == 'state_change':
        vals.setdefault('on_state_change', True)
