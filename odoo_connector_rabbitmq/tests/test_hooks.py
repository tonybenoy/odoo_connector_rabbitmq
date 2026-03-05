import json

from odoo.tests.common import TransactionCase

from ..hooks import (
    _build_rules_cache,
    _invalidate_rules_cache,
    _prepare_payload,
    _serialize_vals,
)


class TestRulesCache(TransactionCase):
    """Tests for the global hook rules cache."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_model = cls.env['ir.model'].search(
            [('model', '=', 'res.partner')], limit=1,
        )
        # Ensure global hook is enabled
        cls.env['ir.config_parameter'].sudo().set_param(
            'odoo_connector_rabbitmq.global_hook_enabled', 'True',
        )

    def _create_rule(self, event_type='create', model_id=None, **kwargs):
        vals = {
            'name': f'Test {event_type}',
            'model_id': model_id or self.partner_model.id,
            'event_type': event_type,
            'exchange_name': 'test_ex',
            'exchange_type': 'topic',
            'routing_key': f'test.partner.{event_type}',
        }
        vals.update(kwargs)
        return self.env['rabbitmq.event.rule'].create(vals)

    def test_build_cache_empty(self):
        """Cache with no rules should be empty dict."""
        # Remove all rules
        self.env['rabbitmq.event.rule'].sudo().search([]).unlink()
        cache = _build_rules_cache(self.env)
        self.assertEqual(cache, {})

    def test_build_cache_with_rule(self):
        self._create_rule('create')
        _invalidate_rules_cache(self.env.registry)
        cache = _build_rules_cache(self.env)
        self.assertIn('res.partner', cache)
        self.assertIn('create', cache['res.partner'])
        rule_data = cache['res.partner']['create'][0]
        self.assertEqual(rule_data['exchange_name'], 'test_ex')
        self.assertEqual(rule_data['routing_key'], 'test.partner.create')

    def test_cache_skips_internal_models(self):
        """Models in _SKIP_MODELS should never appear in cache."""
        log_model = self.env['ir.model'].search(
            [('model', '=', 'rabbitmq.event.log')], limit=1,
        )
        if log_model:
            self._create_rule('create', model_id=log_model.id)
            _invalidate_rules_cache(self.env.registry)
            cache = _build_rules_cache(self.env)
            self.assertNotIn('rabbitmq.event.log', cache)

    def test_cache_disabled_hook(self):
        """When global hook is disabled, cache should be empty."""
        self.env['ir.config_parameter'].sudo().set_param(
            'odoo_connector_rabbitmq.global_hook_enabled', 'False',
        )
        # Flush to ensure the param is visible to _build_rules_cache
        self.env.flush_all()
        _invalidate_rules_cache(self.env.registry)
        cache = _build_rules_cache(self.env)
        self.assertEqual(cache, {})
        # Re-enable for other tests
        self.env['ir.config_parameter'].sudo().set_param(
            'odoo_connector_rabbitmq.global_hook_enabled', 'True',
        )

    def test_invalidate_cache(self):
        registry = self.env.registry
        registry._rabbitmq_rules_cache = {'some': 'data'}
        _invalidate_rules_cache(registry)
        self.assertIsNone(registry._rabbitmq_rules_cache)

    def test_field_names_are_frozenset(self):
        """Tracked field_names should be pre-computed frozensets."""
        field_obj = self.env['ir.model.fields'].search(
            [('model', '=', 'res.partner'), ('name', '=', 'phone')],
            limit=1,
        )
        self._create_rule('write', field_ids=[(6, 0, field_obj.ids)])
        _invalidate_rules_cache(self.env.registry)
        cache = _build_rules_cache(self.env)
        rule_data = cache['res.partner']['write'][0]
        self.assertIsInstance(rule_data['field_names'], frozenset)
        self.assertIn('phone', rule_data['field_names'])


class TestSerializeVals(TransactionCase):
    """Tests for payload serialization helpers."""

    def test_serialize_simple_vals(self):
        result = _serialize_vals({'name': 'Test', 'count': 5})
        self.assertEqual(result['name'], 'Test')
        self.assertEqual(result['count'], 5)

    def test_serialize_non_json(self):
        """Non-JSON-serializable values should be stringified."""
        result = _serialize_vals({'obj': object()})
        self.assertIsInstance(result['obj'], str)

    def test_serialize_recordset(self):
        partner = self.env['res.partner'].create({'name': 'Test'})
        result = _serialize_vals({'partner': partner})
        self.assertEqual(result['partner'], partner.ids)


class TestGlobalHookEvents(TransactionCase):
    """Integration tests: verify ORM operations produce event logs."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner_model = cls.env['ir.model'].search(
            [('model', '=', 'res.partner')], limit=1,
        )
        cls.env['ir.config_parameter'].sudo().set_param(
            'odoo_connector_rabbitmq.global_hook_enabled', 'True',
        )

    def setUp(self):
        super().setUp()
        # Clear old logs and rules
        self.env['rabbitmq.event.log'].sudo().search([]).unlink()
        self.env['rabbitmq.event.rule'].sudo().search([]).unlink()
        _invalidate_rules_cache(self.env.registry)

    def _create_rule(self, event_type):
        return self.env['rabbitmq.event.rule'].create({
            'name': f'Test {event_type}',
            'model_id': self.partner_model.id,
            'event_type': event_type,
            'exchange_name': 'odoo_events',
            'exchange_type': 'topic',
            'routing_key': f'res.partner.{event_type}',
        })

    def _get_logs(self, event_type):
        return self.env['rabbitmq.event.log'].sudo().search([
            ('model_name', '=', 'res.partner'),
            ('event_type', '=', event_type),
        ])

    def test_create_event(self):
        """Creating a partner with a create rule should produce an event log."""
        self._create_rule('create')
        partner = self.env['res.partner'].create({'name': 'Hook Test'})
        logs = self._get_logs('create')
        self.assertTrue(logs)
        payload = json.loads(logs[0].payload)
        self.assertEqual(payload['model'], 'res.partner')
        self.assertIn(partner.id, payload['record_ids'])
        self.assertEqual(logs[0].state, 'pending')
        self.assertEqual(logs[0].exchange_name, 'odoo_events')

    def test_write_event(self):
        """Updating a partner with a write rule should produce an event log."""
        partner = self.env['res.partner'].create({'name': 'Before'})
        self._create_rule('write')
        partner.write({'name': 'After'})
        logs = self._get_logs('write')
        self.assertTrue(logs)
        payload = json.loads(logs[0].payload)
        self.assertIn('name', payload.get('values', {}))

    def test_write_event_field_filter(self):
        """Write rule with field filter should only fire for tracked fields."""
        phone_field = self.env['ir.model.fields'].search(
            [('model', '=', 'res.partner'), ('name', '=', 'phone')],
            limit=1,
        )
        self.env['rabbitmq.event.rule'].create({
            'name': 'Track phone',
            'model_id': self.partner_model.id,
            'event_type': 'write',
            'exchange_name': 'odoo_events',
            'exchange_type': 'topic',
            'routing_key': 'res.partner.write',
            'field_ids': [(6, 0, phone_field.ids)],
        })
        partner = self.env['res.partner'].create({'name': 'Filter Test'})

        # Change name (not tracked) — no event
        partner.write({'name': 'Changed'})
        logs = self._get_logs('write')
        self.assertFalse(logs)

        # Change phone (tracked) — event fires
        partner.write({'phone': '555-1234'})
        logs = self._get_logs('write')
        self.assertTrue(logs)

    def test_unlink_event(self):
        """Deleting a partner with an unlink rule should produce an event log."""
        partner = self.env['res.partner'].create({'name': 'To Delete'})
        self._create_rule('unlink')
        partner.unlink()
        logs = self._get_logs('unlink')
        self.assertTrue(logs)
        payload = json.loads(logs[0].payload)
        self.assertTrue(payload.get('deleted_records'))
        self.assertEqual(payload['deleted_records'][0]['id'], partner.id)

    def test_no_event_without_rule(self):
        """Models without rules should not produce event logs."""
        self.env['res.partner.category'].create({'name': 'No Rule Cat'})
        logs = self.env['rabbitmq.event.log'].sudo().search([
            ('model_name', '=', 'res.partner.category'),
        ])
        self.assertFalse(logs)

    def test_state_change_event(self):
        """State change rule should fire when state field changes."""
        self._create_rule('state_change')
        # res.partner doesn't have state, so write with vals containing 'state'
        # will check old vs new; since field doesn't exist, this tests gracefully
        partner = self.env['res.partner'].create({'name': 'State Test'})
        # The state field won't exist on res.partner — ensure no crash
        partner.write({'name': 'Updated'})
        # No state_change log since 'state' wasn't in vals
        logs = self._get_logs('state_change')
        self.assertFalse(logs)


class TestPreparePayload(TransactionCase):
    """Tests for _prepare_payload helper."""

    def test_basic_payload(self):
        partner = self.env['res.partner'].create({'name': 'Payload Test'})
        payload = _prepare_payload(
            self.env, 'create', 'res.partner', partner,
        )
        self.assertIn('event_id', payload)
        self.assertIn('timestamp', payload)
        self.assertEqual(payload['model'], 'res.partner')
        self.assertEqual(payload['event_type'], 'create')
        self.assertEqual(payload['record_ids'], partner.ids)
        self.assertEqual(payload['database'], self.env.cr.dbname)

    def test_payload_with_vals(self):
        partner = self.env['res.partner'].create({'name': 'Vals Test'})
        payload = _prepare_payload(
            self.env, 'write', 'res.partner', partner,
            vals={'name': 'New'},
            old_vals={'name': 'Old'},
        )
        self.assertEqual(payload['values']['name'], 'New')
        self.assertEqual(payload['old_values']['name'], 'Old')
        self.assertIn('name', payload['changed_fields'])
