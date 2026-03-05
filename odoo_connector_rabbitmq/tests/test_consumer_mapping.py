import json

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase


class TestConsumerRuleValidation(TransactionCase):
    """Tests for consumer rule validation constraints."""

    def test_reject_nonexistent_model(self):
        with self.assertRaises(ValidationError):
            self.env['rabbitmq.consumer.rule'].create({
                'name': 'Bad',
                'queue_name': 'q',
                'target_model': 'nonexistent.model',
                'processing_mode': 'method',
                'target_method': 'handle',
            })

    def test_reject_nonexistent_method(self):
        with self.assertRaises(ValidationError):
            self.env['rabbitmq.consumer.rule'].create({
                'name': 'Bad',
                'queue_name': 'q',
                'target_model': 'res.partner',
                'processing_mode': 'method',
                'target_method': 'this_method_does_not_exist',
            })

    def test_reject_method_mode_without_method(self):
        with self.assertRaises(ValidationError):
            self.env['rabbitmq.consumer.rule'].create({
                'name': 'Bad',
                'queue_name': 'q',
                'target_model': 'res.partner',
                'processing_mode': 'method',
            })

    def test_reject_mapping_write_without_match_field(self):
        with self.assertRaises(ValidationError):
            self.env['rabbitmq.consumer.rule'].create({
                'name': 'Bad',
                'queue_name': 'q',
                'target_model': 'res.partner',
                'processing_mode': 'mapping',
                'consumer_action': 'write',
            })

    def test_reject_mapping_upsert_without_match_field(self):
        with self.assertRaises(ValidationError):
            self.env['rabbitmq.consumer.rule'].create({
                'name': 'Bad',
                'queue_name': 'q',
                'target_model': 'res.partner',
                'processing_mode': 'mapping',
                'consumer_action': 'upsert',
            })

    def test_reject_delete_when_disabled(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'odoo_connector_rabbitmq.consumer_allow_delete', 'False',
        )
        with self.assertRaises(ValidationError):
            self.env['rabbitmq.consumer.rule'].create({
                'name': 'Bad',
                'queue_name': 'q',
                'target_model': 'res.partner',
                'processing_mode': 'mapping',
                'consumer_action': 'unlink',
                'match_field': 'email',
            })

    def test_allow_delete_when_enabled(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'odoo_connector_rabbitmq.consumer_allow_delete', 'True',
        )
        rule = self.env['rabbitmq.consumer.rule'].create({
            'name': 'Delete OK',
            'queue_name': 'q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'unlink',
            'match_field': 'email',
        })
        self.assertTrue(rule.id)

    def test_valid_mapping_create(self):
        rule = self.env['rabbitmq.consumer.rule'].create({
            'name': 'Good',
            'queue_name': 'q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'create',
        })
        self.assertTrue(rule.id)


class TestFieldMappingProcessor(TransactionCase):
    """Tests for _process_message_mapping and type conversion."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.rule = cls.env['rabbitmq.consumer.rule'].create({
            'name': 'Partner Import',
            'queue_name': 'test_q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'create',
            'mapping_ids': [
                (0, 0, {'source_field': 'name', 'target_field': 'name', 'field_type': 'char', 'sequence': 10}),
                (0, 0, {'source_field': 'email', 'target_field': 'email', 'field_type': 'char', 'sequence': 20}),
                (0, 0, {'source_field': 'is_company', 'target_field': 'is_company', 'field_type': 'boolean', 'sequence': 30}),
            ],
        })

    def test_create_action(self):
        msg = json.dumps({'name': 'Alice', 'email': 'alice@example.com', 'is_company': False})
        result = self.rule._process_message_mapping(msg)
        self.assertTrue(result.id)
        self.assertEqual(result.name, 'Alice')
        self.assertEqual(result.email, 'alice@example.com')
        self.assertFalse(result.is_company)

    def test_boolean_conversion(self):
        """Boolean field type should convert strings properly."""
        msg = json.dumps({'name': 'BoolTest', 'email': '', 'is_company': 'true'})
        result = self.rule._process_message_mapping(msg)
        self.assertTrue(result.is_company)

    def test_boolean_conversion_yes(self):
        msg = json.dumps({'name': 'BoolYes', 'email': '', 'is_company': 'yes'})
        result = self.rule._process_message_mapping(msg)
        self.assertTrue(result.is_company)

    def test_boolean_conversion_zero(self):
        msg = json.dumps({'name': 'Bool0', 'email': '', 'is_company': 0})
        result = self.rule._process_message_mapping(msg)
        self.assertFalse(result.is_company)

    def test_payload_root(self):
        """Payload root should navigate nested JSON."""
        rule = self.env['rabbitmq.consumer.rule'].create({
            'name': 'Nested',
            'queue_name': 'q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'create',
            'payload_root': 'data.partner',
            'mapping_ids': [
                (0, 0, {'source_field': 'name', 'target_field': 'name', 'field_type': 'char'}),
            ],
        })
        msg = json.dumps({'data': {'partner': {'name': 'Nested Alice'}}})
        result = rule._process_message_mapping(msg)
        self.assertEqual(result.name, 'Nested Alice')

    def test_dot_notation_source(self):
        """Source field with dot notation should navigate nested keys."""
        rule = self.env['rabbitmq.consumer.rule'].create({
            'name': 'DotNotation',
            'queue_name': 'q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'create',
            'mapping_ids': [
                (0, 0, {'source_field': 'info.full_name', 'target_field': 'name', 'field_type': 'char'}),
            ],
        })
        msg = json.dumps({'info': {'full_name': 'Deep Name'}})
        result = rule._process_message_mapping(msg)
        self.assertEqual(result.name, 'Deep Name')

    def test_default_value(self):
        """Missing source should use default_value."""
        rule = self.env['rabbitmq.consumer.rule'].create({
            'name': 'Defaults',
            'queue_name': 'q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'create',
            'mapping_ids': [
                (0, 0, {
                    'source_field': 'name', 'target_field': 'name',
                    'field_type': 'char', 'default_value': 'Unknown',
                }),
            ],
        })
        msg = json.dumps({'no_name_key': 'x'})
        result = rule._process_message_mapping(msg)
        self.assertEqual(result.name, 'Unknown')

    def test_integer_conversion(self):
        rule = self.env['rabbitmq.consumer.rule'].create({
            'name': 'IntTest',
            'queue_name': 'q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'create',
            'mapping_ids': [
                (0, 0, {'source_field': 'name', 'target_field': 'name', 'field_type': 'char'}),
                (0, 0, {'source_field': 'color', 'target_field': 'color', 'field_type': 'integer'}),
            ],
        })
        msg = json.dumps({'name': 'ColorTest', 'color': '5'})
        result = rule._process_message_mapping(msg)
        self.assertEqual(result.color, 5)

    def test_write_action(self):
        partner = self.env['res.partner'].create({
            'name': 'Original',
            'email': 'orig@test.com',
        })
        rule = self.env['rabbitmq.consumer.rule'].create({
            'name': 'Update',
            'queue_name': 'q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'write',
            'match_field': 'email',
            'mapping_ids': [
                (0, 0, {'source_field': 'email', 'target_field': 'email', 'field_type': 'char'}),
                (0, 0, {'source_field': 'name', 'target_field': 'name', 'field_type': 'char'}),
            ],
        })
        msg = json.dumps({'email': 'orig@test.com', 'name': 'Updated'})
        result = rule._process_message_mapping(msg)
        self.assertEqual(result.id, partner.id)
        self.assertEqual(partner.name, 'Updated')

    def test_upsert_create(self):
        """Upsert should create if no match found."""
        rule = self.env['rabbitmq.consumer.rule'].create({
            'name': 'Upsert',
            'queue_name': 'q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'upsert',
            'match_field': 'email',
            'mapping_ids': [
                (0, 0, {'source_field': 'email', 'target_field': 'email', 'field_type': 'char'}),
                (0, 0, {'source_field': 'name', 'target_field': 'name', 'field_type': 'char'}),
            ],
        })
        msg = json.dumps({'email': 'new@upsert.com', 'name': 'New Partner'})
        result = rule._process_message_mapping(msg)
        self.assertTrue(result.id)
        self.assertEqual(result.email, 'new@upsert.com')

    def test_upsert_update(self):
        """Upsert should update if match found."""
        partner = self.env['res.partner'].create({
            'name': 'Existing',
            'email': 'exist@upsert.com',
        })
        rule = self.env['rabbitmq.consumer.rule'].create({
            'name': 'Upsert',
            'queue_name': 'q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'upsert',
            'match_field': 'email',
            'mapping_ids': [
                (0, 0, {'source_field': 'email', 'target_field': 'email', 'field_type': 'char'}),
                (0, 0, {'source_field': 'name', 'target_field': 'name', 'field_type': 'char'}),
            ],
        })
        msg = json.dumps({'email': 'exist@upsert.com', 'name': 'Upserted'})
        result = rule._process_message_mapping(msg)
        self.assertEqual(result.id, partner.id)
        self.assertEqual(partner.name, 'Upserted')

    def test_unlink_action(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'odoo_connector_rabbitmq.consumer_allow_delete', 'True',
        )
        partner = self.env['res.partner'].create({
            'name': 'ToDelete',
            'email': 'delete@test.com',
        })
        rule = self.env['rabbitmq.consumer.rule'].create({
            'name': 'Delete',
            'queue_name': 'q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'unlink',
            'match_field': 'email',
            'mapping_ids': [
                (0, 0, {'source_field': 'email', 'target_field': 'email', 'field_type': 'char'}),
            ],
        })
        msg = json.dumps({'email': 'delete@test.com'})
        rule._process_message_mapping(msg)
        self.assertFalse(partner.exists())

    def test_invalid_payload_root(self):
        """Invalid payload root should raise ValueError."""
        rule = self.env['rabbitmq.consumer.rule'].create({
            'name': 'BadRoot',
            'queue_name': 'q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'create',
            'payload_root': 'nonexistent.path',
            'mapping_ids': [
                (0, 0, {'source_field': 'name', 'target_field': 'name', 'field_type': 'char'}),
            ],
        })
        with self.assertRaises(ValueError):
            rule._process_message_mapping(json.dumps({'name': 'Test'}))

    def test_write_no_match_raises(self):
        """Write action with no matching record should raise ValueError."""
        rule = self.env['rabbitmq.consumer.rule'].create({
            'name': 'NoMatch',
            'queue_name': 'q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'write',
            'match_field': 'email',
            'mapping_ids': [
                (0, 0, {'source_field': 'email', 'target_field': 'email', 'field_type': 'char'}),
                (0, 0, {'source_field': 'name', 'target_field': 'name', 'field_type': 'char'}),
            ],
        })
        with self.assertRaises(ValueError):
            rule._process_message_mapping(json.dumps({
                'email': 'nonexistent@nowhere.com',
                'name': 'Ghost',
            }))


class TestTypeConversion(TransactionCase):
    """Tests for _convert_mapping_value edge cases."""

    def _make_mapping(self, field_type, **kwargs):
        rule = self.env['rabbitmq.consumer.rule'].create({
            'name': 'TypeTest',
            'queue_name': 'q',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'create',
        })
        vals = {
            'consumer_rule_id': rule.id,
            'source_field': 'x',
            'target_field': 'x',
            'field_type': field_type,
        }
        vals.update(kwargs)
        return self.env['rabbitmq.consumer.field.mapping'].create(vals), rule

    def test_float_conversion(self):
        mapping, rule = self._make_mapping('float')
        result = rule._convert_mapping_value(mapping, '3.14')
        self.assertAlmostEqual(result, 3.14)

    def test_float_invalid(self):
        mapping, rule = self._make_mapping('float')
        result = rule._convert_mapping_value(mapping, 'not_a_number')
        self.assertIsNone(result)

    def test_integer_invalid(self):
        mapping, rule = self._make_mapping('integer')
        result = rule._convert_mapping_value(mapping, 'abc')
        self.assertIsNone(result)

    def test_date_conversion(self):
        mapping, rule = self._make_mapping('date')
        result = rule._convert_mapping_value(mapping, '2025-01-15T10:30:00Z')
        self.assertEqual(result, '2025-01-15')

    def test_datetime_conversion(self):
        mapping, rule = self._make_mapping('datetime')
        result = rule._convert_mapping_value(mapping, '2025-01-15T10:30:00Z')
        self.assertEqual(result, '2025-01-15 10:30:00')

    def test_raw_passthrough(self):
        mapping, rule = self._make_mapping('raw')
        result = rule._convert_mapping_value(mapping, [1, 2, 3])
        self.assertEqual(result, [1, 2, 3])

    def test_many2one_id(self):
        mapping, rule = self._make_mapping('many2one_id')
        result = rule._convert_mapping_value(mapping, '42')
        self.assertEqual(result, 42)

    def test_many2one_search(self):
        mapping, rule = self._make_mapping(
            'many2one_search',
            search_model='res.country',
            search_field='code',
        )
        us = self.env['res.country'].search([('code', '=', 'US')], limit=1)
        result = rule._convert_mapping_value(mapping, 'US')
        self.assertEqual(result, us.id)

    def test_many2one_search_not_found(self):
        mapping, rule = self._make_mapping(
            'many2one_search',
            search_model='res.country',
            search_field='code',
        )
        result = rule._convert_mapping_value(mapping, 'ZZZZZZ')
        self.assertIsNone(result)

    def test_none_with_default(self):
        mapping, rule = self._make_mapping('char', default_value='fallback')
        result = rule._convert_mapping_value(mapping, None)
        self.assertEqual(result, 'fallback')

    def test_char_conversion(self):
        mapping, rule = self._make_mapping('char')
        result = rule._convert_mapping_value(mapping, 42)
        self.assertEqual(result, '42')
