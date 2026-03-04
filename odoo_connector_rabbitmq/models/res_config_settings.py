from odoo import api, fields, models


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
