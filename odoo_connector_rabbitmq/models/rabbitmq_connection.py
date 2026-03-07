import logging
import ssl as ssl_module

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

try:
    import pika
except ImportError:
    pika = None
    _logger.warning('pika library not found. Please install: pip install pika>=1.3.0')


class RabbitMQConnection(models.Model):
    _name = 'rabbitmq.connection'
    _description = 'RabbitMQ Connection'
    _order = 'name'

    name = fields.Char(string='Name', required=True)
    connection_uri = fields.Char(
        string='Connection URI',
        help='Full AMQP URI (e.g. amqp://user:pass@host:5672/vhost). Overrides individual connection fields when set.',
    )
    host = fields.Char(string='Host', default='localhost', required=True)
    port = fields.Integer(string='Port', default=5672, required=True)
    username = fields.Char(string='Username', default='guest')
    password = fields.Char(string='Password', default='guest')
    virtual_host = fields.Char(string='Virtual Host', default='/')
    ssl_enabled = fields.Boolean(string='SSL/TLS Enabled')
    ssl_ca_cert = fields.Binary(string='CA Certificate')
    heartbeat = fields.Integer(string='Heartbeat (seconds)', default=600)
    connection_timeout = fields.Integer(string='Connection Timeout (seconds)', default=10)
    active = fields.Boolean(string='Active', default=True)
    state = fields.Selection(
        [('disconnected', 'Disconnected'), ('connected', 'Connected'), ('error', 'Error')],
        string='Status',
        default='disconnected',
        readonly=True,
    )
    last_error = fields.Text(string='Last Error', readonly=True)

    # --- Computed counts ---
    rule_count = fields.Integer(string='Event Rules', compute='_compute_counts')
    event_count = fields.Integer(string='Events', compute='_compute_counts')

    def _compute_counts(self):
        for conn in self:
            conn.rule_count = self.env['rabbitmq.event.rule'].sudo().search_count([
                ('active', '=', True),
            ])
            conn.event_count = self.env['rabbitmq.event.log'].sudo().search_count([
                ('direction', '=', 'outbound'),
            ])

    def action_view_rules(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Event Rules',
            'res_model': 'rabbitmq.event.rule',
            'view_mode': 'list,form',
        }

    def action_view_events(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Event Logs',
            'res_model': 'rabbitmq.event.log',
            'view_mode': 'list,form',
            'domain': [('direction', '=', 'outbound')],
        }

    def _get_connection_params(self):
        """Build pika connection parameters from this record."""
        self.ensure_one()
        if not pika:
            raise UserError(_('pika library is not installed.'))

        if self.connection_uri:
            return pika.URLParameters(self.connection_uri)

        credentials = pika.PlainCredentials(
            self.username or 'guest',
            self.password or 'guest',
        )
        ssl_options = None
        if self.ssl_enabled:
            ctx = ssl_module.create_default_context()
            if self.ssl_ca_cert:
                import os
                import tempfile

                fd, ca_path = tempfile.mkstemp(suffix='.pem')
                try:
                    os.write(fd, self.ssl_ca_cert)
                    os.close(fd)
                    ctx.load_verify_locations(ca_path)
                finally:
                    if os.path.exists(ca_path):
                        os.unlink(ca_path)
            ssl_options = pika.SSLOptions(ctx, self.host)

        icp = self.env['ir.config_parameter'].sudo()
        blocked_timeout = int(icp.get_param(
            'odoo_connector_rabbitmq.blocked_connection_timeout', '300'))
        conn_attempts = int(icp.get_param(
            'odoo_connector_rabbitmq.connection_attempts', '3'))
        retry_delay = int(icp.get_param(
            'odoo_connector_rabbitmq.retry_delay', '2'))

        return pika.ConnectionParameters(
            host=self.host,
            port=self.port,
            virtual_host=self.virtual_host or '/',
            credentials=credentials,
            heartbeat=self.heartbeat or 600,
            blocked_connection_timeout=blocked_timeout,
            connection_attempts=conn_attempts,
            retry_delay=retry_delay,
            socket_timeout=self.connection_timeout or 10,
            ssl_options=ssl_options,
        )

    def action_test_connection(self):
        """Test the RabbitMQ connection and show result notification."""
        self.ensure_one()
        if not pika:
            raise UserError(_('pika library is not installed.'))

        try:
            params = self._get_connection_params()
            connection = pika.BlockingConnection(params)
            connection.close()
            self.write({'state': 'connected', 'last_error': False})
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Successful'),
                    'message': _('Successfully connected to RabbitMQ at %s:%s', self.host, self.port),
                    'type': 'success',
                    'sticky': False,
                },
            }
        except Exception as e:
            error_msg = str(e)
            self.write({'state': 'error', 'last_error': error_msg})
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Connection Failed'),
                    'message': error_msg,
                    'type': 'danger',
                    'sticky': True,
                },
            }
