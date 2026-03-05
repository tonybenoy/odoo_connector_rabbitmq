import json

from odoo.tests.common import TransactionCase


class TestRabbitmqEventDecorator(TransactionCase):
    """Tests for the @rabbitmq_event decorator."""

    def test_decorator_creates_log(self):
        """Decorated method should create an outbound event log."""
        from ..decorator import rabbitmq_event

        # Dynamically decorate a method and call it
        partner = self.env['res.partner'].create({'name': 'Deco Test'})

        @rabbitmq_event('test_event', exchange='test_ex', routing_key='test.key')
        def fake_method(self_records):
            return True

        fake_method(partner)

        logs = self.env['rabbitmq.event.log'].sudo().search([
            ('model_name', '=', 'res.partner'),
            ('event_type', '=', 'test_event'),
        ])
        self.assertTrue(logs)
        self.assertEqual(logs[0].exchange_name, 'test_ex')
        self.assertEqual(logs[0].routing_key, 'test.key')
        self.assertEqual(logs[0].direction, 'outbound')
        self.assertEqual(logs[0].state, 'pending')
        payload = json.loads(logs[0].payload)
        self.assertEqual(payload['event_type'], 'test_event')
        self.assertIn(partner.id, payload['record_ids'])

    def test_decorator_default_routing_key(self):
        """Without explicit routing_key, should default to model.event_name."""
        from ..decorator import rabbitmq_event

        partner = self.env['res.partner'].create({'name': 'DK Test'})

        @rabbitmq_event('my_event', exchange='ex')
        def fake_method(self_records):
            return None

        fake_method(partner)

        logs = self.env['rabbitmq.event.log'].sudo().search([
            ('event_type', '=', 'my_event'),
        ])
        self.assertTrue(logs)
        self.assertEqual(logs[0].routing_key, 'res.partner.my_event')

    def test_decorator_preserves_return_value(self):
        """Decorator should not alter the wrapped method's return value."""
        from ..decorator import rabbitmq_event

        partner = self.env['res.partner'].create({'name': 'Return Test'})

        @rabbitmq_event('evt')
        def fake_method(self_records):
            return {'key': 'value'}

        result = fake_method(partner)
        self.assertEqual(result, {'key': 'value'})

    def test_decorator_exception_does_not_propagate(self):
        """If logging fails, the original method should still succeed."""
        from ..decorator import rabbitmq_event

        partner = self.env['res.partner'].create({'name': 'Safe Test'})

        @rabbitmq_event('evt', exchange='ex')
        def fake_method(self_records):
            return 42

        # Even if something weird happens internally, return value should be fine
        result = fake_method(partner)
        self.assertEqual(result, 42)
