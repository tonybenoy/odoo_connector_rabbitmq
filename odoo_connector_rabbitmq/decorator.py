import functools
import json
import logging
import uuid

from odoo import fields

_logger = logging.getLogger(__name__)


def rabbitmq_event(event_name, exchange='odoo_events', routing_key=None):
    """Decorator to emit a RabbitMQ event when a method is called.

    Usage::

        from odoo.addons.odoo_connector_rabbitmq.decorator import rabbitmq_event

        class SaleOrder(models.Model):
            _inherit = 'sale.order'

            @rabbitmq_event('order_confirmed', exchange='sales',
                            routing_key='order.confirmed')
            def action_confirm(self):
                return super().action_confirm()

    The decorated method runs normally. After successful execution,
    an outbound event log entry is created with the return value
    as part of the payload.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            result = func(self, *args, **kwargs)

            try:
                payload = {
                    'event_id': str(uuid.uuid4()),
                    'timestamp': fields.Datetime.now().isoformat() + 'Z',
                    'database': self.env.cr.dbname,
                    'model': self._name,
                    'event_type': event_name,
                    'record_ids': self.ids,
                    'user_id': self.env.uid,
                    'user_login': self.env.user.login,
                }
                # Include return value if JSON-serializable
                if result is not None:
                    try:
                        json.dumps(result, default=str)
                        payload['result'] = result
                    except (TypeError, ValueError):
                        payload['result'] = str(result)

                rk = routing_key or f'{self._name}.{event_name}'

                icp = self.env['ir.config_parameter'].sudo()
                max_retries = int(icp.get_param('odoo_connector_rabbitmq.max_retries', '5'))

                self.env['rabbitmq.event.log'].sudo().create({
                    'event_id': payload['event_id'],
                    'direction': 'outbound',
                    'model_name': self._name,
                    'event_type': event_name,
                    'record_ids': json.dumps(self.ids),
                    'payload': json.dumps(payload, default=str),
                    'exchange_name': exchange,
                    'routing_key': rk,
                    'state': 'pending',
                    'max_retries': max_retries,
                })
            except Exception as e:
                _logger.error(
                    "Failed to log RabbitMQ event %s: %s", event_name, e,
                )

            return result
        return wrapper
    return decorator
