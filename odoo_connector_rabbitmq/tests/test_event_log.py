import json
from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class TestEventLog(TransactionCase):
    """Tests for rabbitmq.event.log model."""

    def _create_log(self, **kwargs):
        vals = {
            'direction': 'outbound',
            'model_name': 'res.partner',
            'event_type': 'create',
            'record_ids': json.dumps([1]),
            'payload': json.dumps({'model': 'res.partner', 'event_type': 'create'}),
            'exchange_name': 'test_ex',
            'routing_key': 'test.key',
            'state': 'pending',
            'max_retries': 5,
        }
        vals.update(kwargs)
        return self.env['rabbitmq.event.log'].sudo().create(vals)

    def test_create_log(self):
        log = self._create_log()
        self.assertTrue(log.id)
        self.assertEqual(log.state, 'pending')
        self.assertTrue(log.event_id)

    def test_action_retry(self):
        """action_retry should reset failed/dead events to pending."""
        log = self._create_log(state='failed', retry_count=3, error_message='oops')
        log.action_retry()
        self.assertEqual(log.state, 'pending')
        self.assertEqual(log.retry_count, 0)
        self.assertFalse(log.error_message)

    def test_action_retry_dead(self):
        log = self._create_log(state='dead', retry_count=5)
        log.action_retry()
        self.assertEqual(log.state, 'pending')

    def test_action_retry_all_dead(self):
        self._create_log(state='dead')
        self._create_log(state='dead')
        self._create_log(state='sent')  # should not be affected
        result = self.env['rabbitmq.event.log'].sudo().action_retry_all_dead()
        self.assertEqual(result['type'], 'ir.actions.client')
        dead_count = self.env['rabbitmq.event.log'].sudo().search_count([
            ('state', '=', 'dead'),
        ])
        self.assertEqual(dead_count, 0)

    def test_retry_failed_events(self):
        """Cron should reset failed events past backoff time."""
        log = self._create_log(
            state='failed',
            next_retry_at=fields.Datetime.now() - timedelta(minutes=5),
        )
        self.env['rabbitmq.event.log']._retry_failed_events()
        log.invalidate_recordset()
        self.assertEqual(log.state, 'pending')

    def test_retry_failed_events_not_ready(self):
        """Failed events before their backoff time should NOT be reset."""
        log = self._create_log(
            state='failed',
            next_retry_at=fields.Datetime.now() + timedelta(hours=1),
        )
        self.env['rabbitmq.event.log']._retry_failed_events()
        log.invalidate_recordset()
        self.assertEqual(log.state, 'failed')

    def test_cleanup_old_logs(self):
        """Cron should delete old sent/received logs."""
        self.env['ir.config_parameter'].sudo().set_param(
            'odoo_connector_rabbitmq.log_retention_days', '1',
        )
        # Create an old sent log (we fake the date by writing directly)
        log = self._create_log(state='sent')
        cutoff = fields.Datetime.now() - timedelta(days=2)
        self.env.cr.execute(
            "UPDATE rabbitmq_event_log SET create_date = %s WHERE id = %s",
            (cutoff, log.id),
        )
        # Also create a recent sent log that should NOT be deleted
        recent = self._create_log(state='sent')

        self.env['rabbitmq.event.log']._cleanup_old_logs()

        self.assertFalse(log.exists())
        self.assertTrue(recent.exists())

    def test_cleanup_preserves_pending(self):
        """Cleanup should not touch pending/failed/dead events."""
        log = self._create_log(state='pending')
        cutoff = fields.Datetime.now() - timedelta(days=100)
        self.env.cr.execute(
            "UPDATE rabbitmq_event_log SET create_date = %s WHERE id = %s",
            (cutoff, log.id),
        )
        self.env['rabbitmq.event.log']._cleanup_old_logs()
        self.assertTrue(log.exists())
