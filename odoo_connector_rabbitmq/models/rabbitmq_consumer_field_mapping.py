from odoo import fields, models


class RabbitMQConsumerFieldMapping(models.Model):
    _name = 'rabbitmq.consumer.field.mapping'
    _description = 'RabbitMQ Consumer Field Mapping'
    _order = 'sequence, id'

    consumer_rule_id = fields.Many2one(
        'rabbitmq.consumer.rule',
        string='Consumer Rule',
        required=True,
        ondelete='cascade',
    )
    sequence = fields.Integer(string='Sequence', default=10)
    source_field = fields.Char(
        string='Source Field',
        required=True,
        help='JSON key from the message payload (dot notation supported, e.g. "address.city").',
    )
    target_field = fields.Char(
        string='Target Field',
        required=True,
        help='Odoo field name on the target model.',
    )
    field_type = fields.Selection(
        [
            ('char', 'Text'),
            ('integer', 'Integer'),
            ('float', 'Float'),
            ('boolean', 'Boolean'),
            ('date', 'Date'),
            ('datetime', 'Datetime'),
            ('many2one_id', 'Many2One (by ID)'),
            ('many2one_search', 'Many2One (by Search)'),
            ('raw', 'Raw (no conversion)'),
        ],
        string='Field Type',
        default='char',
        required=True,
    )
    search_model = fields.Char(
        string='Search Model',
        help='Model to search in for many2one_search type (e.g. res.country).',
    )
    search_field = fields.Char(
        string='Search Field',
        help='Field to search on for many2one_search type (e.g. code).',
    )
    default_value = fields.Char(
        string='Default Value',
        help='Fallback value if the source field is missing or empty.',
    )
