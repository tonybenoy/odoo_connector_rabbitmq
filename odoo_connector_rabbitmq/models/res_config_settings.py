from odoo import fields, models

from ..hooks import _invalidate_rules_cache


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rabbitmq_connection_id = fields.Many2one(
        'rabbitmq.connection',
        string='Default Connection',
        config_parameter='odoo_connector_rabbitmq.default_connection_id',
    )
    rabbitmq_publish_enabled = fields.Boolean(
        string='Enable Publishing',
        config_parameter='odoo_connector_rabbitmq.publish_enabled',
        default=True,
    )
    rabbitmq_global_hook_enabled = fields.Boolean(
        string='Enable Global Hook',
        config_parameter='odoo_connector_rabbitmq.global_hook_enabled',
        default=True,
        help='When disabled, the global BaseModel hook will not capture any events. '
        'Event rules will have no effect until re-enabled. '
        'Requires a cache rebuild (toggle any event rule or restart).',
    )
    rabbitmq_consume_enabled = fields.Boolean(
        string='Enable Consuming',
        config_parameter='odoo_connector_rabbitmq.consume_enabled',
        default=True,
    )
    rabbitmq_consumer_interval = fields.Integer(
        string='Consumer Interval (minutes)',
        config_parameter='odoo_connector_rabbitmq.consumer_interval',
        default=2,
    )
    rabbitmq_consumer_allow_delete = fields.Boolean(
        string='Allow Delete via Field Mapping',
        config_parameter='odoo_connector_rabbitmq.consumer_allow_delete',
        default=False,
        help='When disabled, consumer rules cannot use the Delete action in field mapping mode. '
        'This prevents accidental data deletion from inbound messages.',
    )
    rabbitmq_log_retention_days = fields.Integer(
        string='Log Retention (days)',
        config_parameter='odoo_connector_rabbitmq.log_retention_days',
        default=30,
    )
    rabbitmq_max_retries = fields.Integer(
        string='Max Retries',
        config_parameter='odoo_connector_rabbitmq.max_retries',
        default=5,
    )
    rabbitmq_blocked_connection_timeout = fields.Integer(
        string='Blocked Connection Timeout (seconds)',
        config_parameter='odoo_connector_rabbitmq.blocked_connection_timeout',
        default=300,
        help='Timeout for blocked connections (e.g. when RabbitMQ is under memory alarm).',
    )
    rabbitmq_connection_attempts = fields.Integer(
        string='Connection Attempts',
        config_parameter='odoo_connector_rabbitmq.connection_attempts',
        default=3,
        help='Number of connection attempts before giving up.',
    )
    rabbitmq_retry_delay = fields.Integer(
        string='Retry Delay (seconds)',
        config_parameter='odoo_connector_rabbitmq.retry_delay',
        default=2,
        help='Delay between connection retry attempts.',
    )

    def set_values(self):
        """Invalidate the rules cache when settings change."""
        result = super().set_values()
        _invalidate_rules_cache(self.env.registry)
        return result
