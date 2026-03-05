{
    'name': 'Odoo Connector RabbitMQ',
    'version': '19.0.1.0.0',
    'category': 'Technical',
    'summary': 'Production-grade event-driven architecture via RabbitMQ',
    'description': """
RabbitMQ Event Bus for Odoo
===========================

Production-grade event-driven architecture with:
- Connection pooling with heartbeats and auto-reconnect
- Transactional outbox pattern for reliable delivery
- Retry with exponential backoff and dead-letter handling
- SSL/TLS and cluster URI support
- Full monitoring UI with event log viewer
- Multi-worker safe (cron-based, no daemon threads)
    """,
    'author': 'Tony',
    'depends': ['base', 'base_setup'],
    'external_dependencies': {'python': ['pika']},
    'data': [
        'security/rabbitmq_security.xml',
        'security/ir.model.access.csv',
        'data/rabbitmq_data.xml',
        'data/cron_data.xml',
        'views/rabbitmq_connection_views.xml',
        'views/rabbitmq_event_rule_views.xml',
        'views/rabbitmq_consumer_rule_views.xml',
        'views/rabbitmq_event_log_views.xml',
        'views/res_config_settings_views.xml',
        'views/menu.xml',
    ],
    'post_load': 'post_load',
    'license': 'Other OSI approved licence',
    'installable': True,
    'application': True,
}
