from odoo import fields, models


class RabbitMQConsumerRule(models.Model):
    _name = 'rabbitmq.consumer.rule'
    _description = 'RabbitMQ Consumer Rule'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    queue_name = fields.Char(string='Queue', required=True)
    exchange_name = fields.Char(string='Exchange')
    routing_key = fields.Char(string='Binding Key')
    target_model = fields.Char(
        string='Target Model', required=True,
        help='Odoo model technical name (e.g. res.partner).',
    )
    target_method = fields.Char(
        string='Target Method', required=True,
        help='Method to invoke on the target model. '
             'Method receives (body, properties) as arguments.',
    )
    prefetch_count = fields.Integer(
        string='Messages per Batch', default=10,
        help='Maximum number of messages to process per cron cycle.',
    )
    auto_ack = fields.Boolean(
        string='Auto Acknowledge', default=False,
        help='Automatically acknowledge messages after processing.',
    )
    active = fields.Boolean(string='Active', default=True)
