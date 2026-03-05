import logging
import uuid
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class RabbitMQEventLog(models.Model):
    _name = 'rabbitmq.event.log'
    _description = 'RabbitMQ Event Log'
    _order = 'create_date desc'

    event_id = fields.Char(
        string='Event ID',
        readonly=True,
        default=lambda self: str(uuid.uuid4()),
        copy=False,
        index=True,
    )
    direction = fields.Selection(
        [('outbound', 'Outbound'), ('inbound', 'Inbound')],
        string='Direction',
        required=True,
        readonly=True,
        index=True,
    )
    model_name = fields.Char(string='Model', readonly=True, index=True)
    event_type = fields.Char(string='Event Type', readonly=True, index=True)
    record_ids = fields.Text(string='Record IDs', readonly=True)
    payload = fields.Text(string='Payload', readonly=True)
    exchange_name = fields.Char(string='Exchange', readonly=True)
    routing_key = fields.Char(string='Routing Key', readonly=True)
    queue_name = fields.Char(string='Queue', readonly=True)
    state = fields.Selection(
        [('pending', 'Pending'), ('sent', 'Sent'), ('received', 'Received'), ('failed', 'Failed'), ('dead', 'Dead')],
        string='State',
        default='pending',
        required=True,
        readonly=True,
        index=True,
    )
    error_message = fields.Text(string='Error', readonly=True)
    retry_count = fields.Integer(string='Retry Count', default=0, readonly=True)
    max_retries = fields.Integer(string='Max Retries', default=5, readonly=True)
    next_retry_at = fields.Datetime(string='Next Retry At', readonly=True)

    def action_retry(self):
        """Reset a single event to pending for retry."""
        for record in self:
            record.write(
                {
                    'state': 'pending',
                    'error_message': False,
                    'retry_count': 0,
                    'next_retry_at': False,
                }
            )

    def action_retry_all_dead(self):
        """Reset all dead events to pending."""
        dead_events = self.search([('state', '=', 'dead')])
        dead_events.action_retry()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Dead Events Retried'),
                'message': _('%d events reset to pending.', len(dead_events)),
                'type': 'info',
                'sticky': False,
            },
        }

    @api.model
    def _process_pending_outbound(self):
        """Cron: Publish pending outbound events to RabbitMQ."""
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param('odoo_connector_rabbitmq.publish_enabled', 'True') != 'True':
            return

        # SELECT FOR UPDATE SKIP LOCKED to prevent double-publish in multi-worker
        self.env.cr.execute("""
            SELECT id FROM rabbitmq_event_log
            WHERE state = 'pending'
              AND direction = 'outbound'
              AND (next_retry_at IS NULL OR next_retry_at <= NOW())
            ORDER BY create_date
            LIMIT 100
            FOR UPDATE SKIP LOCKED
        """)
        event_ids = [row[0] for row in self.env.cr.fetchall()]
        if not event_ids:
            return

        events = self.browse(event_ids)
        service = self.env['rabbitmq.service']

        for event in events:
            try:
                service._publish(
                    exchange=event.exchange_name,
                    routing_key=event.routing_key,
                    body=event.payload,
                )
                event.write({'state': 'sent', 'error_message': False})
                _logger.info(
                    'RabbitMQ event %s published to %s/%s',
                    event.event_id,
                    event.exchange_name,
                    event.routing_key,
                )
            except Exception as e:
                error_msg = str(e)
                retry_count = event.retry_count + 1
                if retry_count >= event.max_retries:
                    event.write(
                        {
                            'state': 'dead',
                            'error_message': error_msg,
                            'retry_count': retry_count,
                        }
                    )
                    _logger.error(
                        'RabbitMQ event %s dead after %d retries: %s',
                        event.event_id,
                        retry_count,
                        error_msg,
                    )
                else:
                    backoff_seconds = (2**retry_count) * 60
                    next_retry = fields.Datetime.now() + timedelta(seconds=backoff_seconds)
                    event.write(
                        {
                            'state': 'failed',
                            'error_message': error_msg,
                            'retry_count': retry_count,
                            'next_retry_at': next_retry,
                        }
                    )
                    _logger.warning(
                        'RabbitMQ event %s failed (retry %d/%d), next retry at %s: %s',
                        event.event_id,
                        retry_count,
                        event.max_retries,
                        next_retry,
                        error_msg,
                    )
                # Force reconnect on next attempt
                service._close_connection()

        self.env.cr.commit()

    @api.model
    def _process_inbound(self):
        """Cron: Consume messages from all active consumer rules."""
        icp = self.env['ir.config_parameter'].sudo()
        if icp.get_param('odoo_connector_rabbitmq.consume_enabled', 'True') != 'True':
            return

        rules = (
            self.env['rabbitmq.consumer.rule']
            .sudo()
            .search(
                [('active', '=', True)],
            )
        )
        if not rules:
            return

        service = self.env['rabbitmq.service']

        for rule in rules:
            try:
                channel, messages = service._consume_batch(
                    queue_name=rule.queue_name,
                    exchange_name=rule.exchange_name,
                    routing_key=rule.routing_key,
                    prefetch_count=rule.prefetch_count,
                )
            except Exception as e:
                _logger.error(
                    'RabbitMQ consume failed for rule %s: %s',
                    rule.name,
                    e,
                )
                service._close_connection()
                continue

            if not messages:
                try:
                    channel.close()
                except Exception:
                    pass
                continue

            target_model = self.env.get(rule.target_model)
            if target_model is None:
                _logger.error('Target model %s not found for rule %s', rule.target_model, rule.name)
                # Nack all messages and requeue
                for method, _properties, _body in messages:
                    service._nack_message(channel, method.delivery_tag, requeue=True)
                try:
                    channel.close()
                except Exception:
                    pass
                continue

            for method, properties, body in messages:
                body_str = body.decode('utf-8') if isinstance(body, bytes) else body
                log_vals = {
                    'direction': 'inbound',
                    'queue_name': rule.queue_name,
                    'exchange_name': rule.exchange_name or '',
                    'routing_key': rule.routing_key or '',
                    'payload': body_str,
                    'model_name': rule.target_model,
                    'event_type': 'consume',
                }
                try:
                    if rule.processing_mode == 'mapping':
                        rule._process_message_mapping(body_str)
                    else:
                        target_method = getattr(
                            target_model.sudo(),
                            rule.target_method,
                        )
                        target_method(body_str, properties)
                    service._ack_message(channel, method.delivery_tag)
                    log_vals['state'] = 'received'
                    _logger.info(
                        'RabbitMQ inbound message processed for %s (%s)',
                        rule.target_model,
                        rule.processing_mode,
                    )
                except Exception as e:
                    service._nack_message(channel, method.delivery_tag, requeue=True)
                    log_vals['state'] = 'failed'
                    log_vals['error_message'] = str(e)
                    _logger.error(
                        'RabbitMQ inbound message processing failed: %s',
                        e,
                    )

                self.sudo().create(log_vals)

            try:
                channel.close()
            except Exception:
                pass

        self.env.cr.commit()

    @api.model
    def _retry_failed_events(self):
        """Cron: Re-attempt failed outbound events past their backoff time."""
        events = self.search(
            [
                ('state', '=', 'failed'),
                ('direction', '=', 'outbound'),
                ('next_retry_at', '<=', fields.Datetime.now()),
            ]
        )
        if events:
            events.write({'state': 'pending'})
            _logger.info('RabbitMQ: %d failed events reset to pending for retry', len(events))

    @api.model
    def _cleanup_old_logs(self):
        """Cron: Delete old sent/received event logs."""
        icp = self.env['ir.config_parameter'].sudo()
        days = int(icp.get_param('odoo_connector_rabbitmq.log_retention_days', '30'))
        cutoff = fields.Datetime.now() - timedelta(days=days)
        old_logs = self.search(
            [
                ('state', 'in', ['sent', 'received']),
                ('create_date', '<', cutoff),
            ]
        )
        count = len(old_logs)
        if old_logs:
            old_logs.unlink()
            _logger.info('RabbitMQ: cleaned up %d old event logs', count)
