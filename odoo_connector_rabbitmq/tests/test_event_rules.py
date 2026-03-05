from odoo.tests.common import TransactionCase


class TestEventRule(TransactionCase):
    """Tests for rabbitmq.event.rule model."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_model = cls.env['ir.model'].search(
            [('model', '=', 'res.partner')], limit=1,
        )

    def _create_rule(self, event_type='create', **kwargs):
        vals = {
            'name': f'Test {event_type} Rule',
            'model_id': self.partner_model.id,
            'event_type': event_type,
            'exchange_name': 'test_exchange',
            'exchange_type': 'topic',
            'routing_key': 'test.{model}.{event}',
        }
        vals.update(kwargs)
        return self.env['rabbitmq.event.rule'].create(vals)

    def test_create_rule(self):
        rule = self._create_rule()
        self.assertTrue(rule.id)
        self.assertEqual(rule.model_name, 'res.partner')
        self.assertTrue(rule.active)

    def test_routing_key_placeholders(self):
        rule = self._create_rule(
            event_type='write',
            routing_key='odoo.{model}.{event}',
        )
        resolved = rule._get_routing_key()
        self.assertEqual(resolved, 'odoo.res.partner.write')

    def test_routing_key_empty(self):
        rule = self._create_rule(routing_key='')
        self.assertEqual(rule._get_routing_key(), '')

    def test_cache_invalidation_on_create(self):
        """Creating a rule should invalidate the cache."""
        registry = self.env.registry
        registry._rabbitmq_rules_cache = {'stale': True}
        self._create_rule()
        self.assertIsNone(
            getattr(registry, '_rabbitmq_rules_cache', 'NOT_SET'),
        )

    def test_cache_invalidation_on_write(self):
        rule = self._create_rule()
        self.env.registry._rabbitmq_rules_cache = {'stale': True}
        rule.write({'name': 'Updated'})
        self.assertIsNone(
            getattr(self.env.registry, '_rabbitmq_rules_cache', 'NOT_SET'),
        )

    def test_cache_invalidation_on_unlink(self):
        rule = self._create_rule()
        self.env.registry._rabbitmq_rules_cache = {'stale': True}
        rule.unlink()
        self.assertIsNone(
            getattr(self.env.registry, '_rabbitmq_rules_cache', 'NOT_SET'),
        )

    def test_deactivate_rule(self):
        rule = self._create_rule()
        rule.write({'active': False})
        self.assertFalse(rule.active)
