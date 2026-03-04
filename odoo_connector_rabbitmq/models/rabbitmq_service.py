import logging

from odoo import api, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import pika
except ImportError:
    pika = None


class RabbitMQService(models.AbstractModel):
    _name = 'rabbitmq.service'
    _description = 'RabbitMQ Service Engine'

    def _get_default_connection(self):
        """Get the default RabbitMQ connection record."""
        icp = self.env['ir.config_parameter'].sudo()
        conn_id = icp.get_param('odoo_connector_rabbitmq.default_connection_id')
        if conn_id:
            conn = self.env['rabbitmq.connection'].sudo().browse(int(conn_id))
            if conn.exists() and conn.active:
                return conn
        # Fallback: first active connection
        return self.env['rabbitmq.connection'].sudo().search(
            [('active', '=', True)], limit=1,
        )

    def _get_connection(self):
        """Get or create a cached pika BlockingConnection.

        The connection is cached on the registry to survive across
        cron invocations within the same worker process.
        """
        if not pika:
            raise UserError(_("pika library is not installed."))

        registry = self.env.registry
        connection = getattr(registry, '_rabbitmq_connection', None)

        if connection and connection.is_open:
            return connection

        conn_record = self._get_default_connection()
        if not conn_record:
            raise UserError(_(
                "No active RabbitMQ connection configured. "
                "Go to RabbitMQ > Configuration > Connections to set one up."
            ))

        try:
            params = conn_record._get_connection_params()
            connection = pika.BlockingConnection(params)
            registry._rabbitmq_connection = connection
            conn_record.sudo().write({'state': 'connected', 'last_error': False})
            _logger.info("RabbitMQ connection established to %s:%s",
                         conn_record.host, conn_record.port)
            return connection
        except Exception as e:
            conn_record.sudo().write({'state': 'error', 'last_error': str(e)})
            _logger.error("RabbitMQ connection failed: %s", e)
            raise

    def _get_channel(self):
        """Get a channel from the current connection, reconnecting if needed."""
        connection = self._get_connection()
        try:
            channel = connection.channel()
            channel.confirm_delivery()
            return channel
        except Exception:
            # Connection may have dropped; force reconnect
            registry = self.env.registry
            registry._rabbitmq_connection = None
            connection = self._get_connection()
            channel = connection.channel()
            channel.confirm_delivery()
            return channel

    def _close_connection(self):
        """Gracefully close the cached connection."""
        registry = self.env.registry
        connection = getattr(registry, '_rabbitmq_connection', None)
        if connection and connection.is_open:
            try:
                connection.close()
            except Exception:
                pass
        registry._rabbitmq_connection = None

    def _ensure_exchange(self, channel, name, exchange_type='direct'):
        """Declare an exchange idempotently."""
        channel.exchange_declare(
            exchange=name,
            exchange_type=exchange_type,
            durable=True,
        )

    def _ensure_queue(self, channel, queue_name, exchange_name=None, routing_key=None):
        """Declare a queue and optionally bind it to an exchange."""
        channel.queue_declare(queue=queue_name, durable=True)
        if exchange_name:
            channel.queue_bind(
                queue=queue_name,
                exchange=exchange_name,
                routing_key=routing_key or '',
            )

    def _publish(self, exchange, routing_key, body, content_type='application/json'):
        """Publish a message to RabbitMQ with publisher confirms.

        Args:
            exchange: Exchange name
            routing_key: Routing key
            body: Message body (string)
            content_type: MIME type (default: application/json)

        Returns:
            True if published successfully

        Raises:
            Exception on publish failure
        """
        channel = self._get_channel()
        try:
            self._ensure_exchange(channel, exchange)
            properties = pika.BasicProperties(
                delivery_mode=2,  # persistent
                content_type=content_type,
            )
            channel.basic_publish(
                exchange=exchange,
                routing_key=routing_key,
                body=body,
                properties=properties,
                mandatory=False,
            )
            return True
        finally:
            try:
                channel.close()
            except Exception:
                pass

    def _consume_batch(self, queue_name, exchange_name=None, routing_key=None,
                       prefetch_count=10):
        """Consume up to prefetch_count messages from a queue.

        Returns:
            List of (method, properties, body) tuples
        """
        channel = self._get_channel()
        try:
            if exchange_name:
                self._ensure_exchange(channel, exchange_name)
            self._ensure_queue(channel, queue_name, exchange_name, routing_key)
            channel.basic_qos(prefetch_count=prefetch_count)

            messages = []
            for _ in range(prefetch_count):
                method, properties, body = channel.basic_get(
                    queue=queue_name, auto_ack=False,
                )
                if method is None:
                    break
                messages.append((method, properties, body))
            return channel, messages
        except Exception:
            try:
                channel.close()
            except Exception:
                pass
            raise

    def _ack_message(self, channel, delivery_tag):
        """Acknowledge a message."""
        channel.basic_ack(delivery_tag=delivery_tag)

    def _nack_message(self, channel, delivery_tag, requeue=True):
        """Negative-acknowledge a message."""
        channel.basic_nack(delivery_tag=delivery_tag, requeue=requeue)
