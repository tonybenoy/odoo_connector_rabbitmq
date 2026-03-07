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
            'exchange_name': 'test_exchange',
            'exchange_type': 'topic',
            'routing_key': 'test.{model}.{event}',
        }
        # Map legacy event_type to boolean flags
        if 'on_create' not in kwargs and 'on_write' not in kwargs \
                and 'on_unlink' not in kwargs and 'on_state_change' not in kwargs:
            if event_type == 'create':
                vals['on_create'] = True
            elif event_type == 'write':
                vals['on_write'] = True
            elif event_type == 'unlink':
                vals['on_unlink'] = True
            elif event_type == 'state_change':
                vals['on_state_change'] = True
        vals.update(kwargs)
        return self.env['rabbitmq.event.rule'].create(vals)

    def test_create_rule(self):
        rule = self._create_rule()
        self.assertTrue(rule.id)
        self.assertEqual(rule.model_name, 'res.partner')
        self.assertTrue(rule.active)
        self.assertTrue(rule.on_create)

    def test_routing_key_placeholders(self):
        rule = self._create_rule(
            event_type='write',
            routing_key='odoo.{model}.{event}',
        )
        resolved = rule._get_routing_key(event_type='write')
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

    def test_crud_checkboxes_multiple(self):
        """A single rule can track multiple event types."""
        rule = self._create_rule(
            on_create=True,
            on_write=True,
            on_unlink=True,
        )
        types = rule._get_enabled_event_types()
        self.assertIn('create', types)
        self.assertIn('write', types)
        self.assertIn('unlink', types)
        self.assertNotIn('state_change', types)

    def test_legacy_event_type_fallback(self):
        """Legacy event_type field still works when no booleans are set."""
        rule = self.env['rabbitmq.event.rule'].create({
            'name': 'Legacy Rule',
            'model_id': self.partner_model.id,
            'event_type': 'create',
            'on_create': False,
            'on_write': False,
            'on_unlink': False,
            'on_state_change': False,
            'exchange_name': 'test_exchange',
        })
        types = rule._get_enabled_event_types()
        self.assertEqual(types, ['create'])

    def test_legacy_event_type_auto_migrated(self):
        """Legacy event_type in vals auto-sets boolean flags."""
        rule = self.env['rabbitmq.event.rule'].create({
            'name': 'Auto Migrate Rule',
            'model_id': self.partner_model.id,
            'event_type': 'write',
            'exchange_name': 'test_exchange',
        })
        self.assertTrue(rule.on_write)

    def test_event_count_stat(self):
        """Event count should be computable without errors."""
        rule = self._create_rule()
        self.assertIsInstance(rule.event_count, int)
