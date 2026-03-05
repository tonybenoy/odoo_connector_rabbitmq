#!/usr/bin/env python3
"""Integration test: verify actual RabbitMQ publishing and consuming across Odoo versions.

Usage:
    python3 test_integration.py <odoo_port> <rabbitmq_host> <db_name>

Example:
    python3 test_integration.py 17069 integ17-rabbitmq integ17
"""
import json
import sys
import time
import xmlrpc.client

ADMIN_PASSWORD = 'admin'


def xmlrpc_call(url, db, uid, password, model, method, *args, **kwargs):
    """Call Odoo XML-RPC."""
    proxy = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
    return proxy.execute_kw(db, uid, password, model, method, list(args), kwargs)


def wait_for_odoo(url, timeout=120):
    """Wait for Odoo to be ready."""
    print(f'  Waiting for Odoo at {url}...', end='', flush=True)
    start = time.time()
    while time.time() - start < timeout:
        try:
            xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common').version()
            print(' ready')
            return True
        except Exception:
            time.sleep(2)
            print('.', end='', flush=True)
    print(' TIMEOUT')
    return False


def authenticate(url, db):
    """Authenticate as admin."""
    common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
    uid = common.authenticate(db, 'admin', ADMIN_PASSWORD, {})
    if not uid:
        raise RuntimeError(f'Authentication failed for db={db}')
    return uid


def trigger_outbound_cron(call):
    """Trigger the outbound processing cron job."""
    cron_ids = call('ir.cron', 'search', [
        ('name', 'ilike', 'Process Outbound'),
    ])
    if cron_ids:
        call('ir.cron', 'method_direct_trigger', cron_ids)
        time.sleep(2)
        return True
    return False


def run_tests(odoo_port, rabbitmq_container, db_name):
    url = f'http://localhost:{odoo_port}'

    if not wait_for_odoo(url):
        return False

    uid = authenticate(url, db_name)
    print(f'  Authenticated as uid={uid}')

    def call(model, method, *args, **kw):
        return xmlrpc_call(url, db_name, uid, ADMIN_PASSWORD, model, method, *args, **kw)

    results = []

    # ── Test 1: Configure RabbitMQ connection ──
    print('\n  [Test 1] Configure RabbitMQ connection...')
    try:
        conn_id = call('rabbitmq.connection', 'create', {
            'name': 'Integration Test',
            'host': rabbitmq_container,
            'port': 5672,
            'username': 'guest',
            'password': 'guest',
            'virtual_host': '/',
        })
        if isinstance(conn_id, list):
            conn_id = conn_id[0]
        print(f'    Created connection id={conn_id}')

        # Test the connection
        call('rabbitmq.connection', 'action_test_connection', [conn_id])
        conn_state = call('rabbitmq.connection', 'read', [conn_id], fields=['state'])
        state = conn_state[0]['state']
        ok = state == 'connected'
        print(f'    Connection state: {state} {"PASS" if ok else "FAIL"}')
        results.append(('Connection test', ok))
    except Exception as e:
        print(f'    FAIL: {e}')
        results.append(('Connection test', False))
        return results

    # ── Test 2: Set as default connection via ir.config_parameter ──
    print('\n  [Test 2] Set default connection...')
    try:
        call('ir.config_parameter', 'set_param',
             'odoo_connector_rabbitmq.default_connection_id', str(conn_id))
        call('ir.config_parameter', 'set_param',
             'odoo_connector_rabbitmq.publish_enabled', 'True')
        call('ir.config_parameter', 'set_param',
             'odoo_connector_rabbitmq.global_hook_enabled', 'True')
        print('    Default connection set. PASS')
        results.append(('Set default connection', True))
    except Exception as e:
        print(f'    FAIL: {e}')
        results.append(('Set default connection', False))

    # ── Test 3: Create an event rule for res.partner create ──
    print('\n  [Test 3] Create event rule for res.partner create...')
    try:
        partner_model_ids = call('ir.model', 'search', [('model', '=', 'res.partner')])
        partner_model_id = partner_model_ids[0]

        rule_id = call('rabbitmq.event.rule', 'create', {
            'name': 'Test Partner Create',
            'model_id': partner_model_id,
            'event_type': 'create',
            'exchange_name': 'integ_test_exchange',
            'exchange_type': 'topic',
            'routing_key': 'partner.created',
            'active': True,
        })
        if isinstance(rule_id, list):
            rule_id = rule_id[0]
        print(f'    Created event rule id={rule_id}. PASS')
        results.append(('Create event rule', True))
    except Exception as e:
        print(f'    FAIL: {e}')
        results.append(('Create event rule', False))

    # ── Test 4: Create a partner and check that an event log is created ──
    print('\n  [Test 4] Create partner → verify event log...')
    try:
        partner_id = call('res.partner', 'create', {
            'name': 'Integration Test Partner',
            'email': 'integ@test.com',
        })
        if isinstance(partner_id, list):
            partner_id = partner_id[0]
        print(f'    Created partner id={partner_id}')

        time.sleep(1)
        log_ids = call('rabbitmq.event.log', 'search', [
            ('model_name', '=', 'res.partner'),
            ('event_type', '=', 'create'),
            ('direction', '=', 'outbound'),
        ])
        ok = len(log_ids) > 0
        if ok:
            log = call('rabbitmq.event.log', 'read', [log_ids[0]],
                        fields=['state', 'exchange_name', 'routing_key', 'payload'])
            print(f'    Event log found: state={log[0]["state"]}, '
                  f'exchange={log[0]["exchange_name"]}, '
                  f'routing_key={log[0]["routing_key"]}')
            payload = json.loads(log[0]['payload'])
            has_data = 'record_ids' in payload or 'vals' in payload or 'data' in payload
            print(f'    Payload has data: {has_data}')
        else:
            print('    No event log found!')
        print(f'    {"PASS" if ok else "FAIL"}')
        results.append(('Event log created on partner create', ok))
    except Exception as e:
        print(f'    FAIL: {e}')
        results.append(('Event log created on partner create', False))

    # ── Test 5: Trigger cron to publish events to RabbitMQ ──
    print('\n  [Test 5] Publish events via cron...')
    try:
        triggered = trigger_outbound_cron(call)
        if not triggered:
            print('    Could not find outbound cron job! FAIL')
            results.append(('Publish to RabbitMQ', False))
        else:
            log_ids = call('rabbitmq.event.log', 'search', [
                ('model_name', '=', 'res.partner'),
                ('event_type', '=', 'create'),
                ('direction', '=', 'outbound'),
            ])
            if log_ids:
                log = call('rabbitmq.event.log', 'read', [log_ids[0]], fields=['state', 'error_message'])
                state = log[0]['state']
                ok = state == 'sent'
                if not ok:
                    err = log[0].get('error_message', '')
                    print(f'    Error: {err}')
                print(f'    Event state after publish: {state} {"PASS" if ok else "FAIL"}')
            else:
                ok = False
                print('    No event log found! FAIL')
            results.append(('Publish to RabbitMQ', ok))
    except Exception as e:
        print(f'    FAIL: {e}')
        results.append(('Publish to RabbitMQ', False))

    # ── Test 6: Create a write event rule and test write capture ──
    print('\n  [Test 6] Create write rule → update partner → verify event...')
    try:
        write_rule_id = call('rabbitmq.event.rule', 'create', {
            'name': 'Test Partner Write',
            'model_id': partner_model_id,
            'event_type': 'write',
            'exchange_name': 'integ_test_exchange',
            'exchange_type': 'topic',
            'routing_key': 'partner.updated',
            'active': True,
        })
        if isinstance(write_rule_id, list):
            write_rule_id = write_rule_id[0]

        call('res.partner', 'write', [partner_id], {'name': 'Updated Integration Test Partner'})
        time.sleep(1)

        write_log_ids = call('rabbitmq.event.log', 'search', [
            ('model_name', '=', 'res.partner'),
            ('event_type', '=', 'write'),
            ('direction', '=', 'outbound'),
        ])
        ok = len(write_log_ids) > 0
        if ok:
            print(f'    Write event log found (id={write_log_ids[0]})')
            trigger_outbound_cron(call)
            log = call('rabbitmq.event.log', 'read', [write_log_ids[0]], fields=['state'])
            print(f'    State after publish: {log[0]["state"]}')
            ok = log[0]['state'] == 'sent'
        print(f'    {"PASS" if ok else "FAIL"}')
        results.append(('Write event capture and publish', ok))
    except Exception as e:
        print(f'    FAIL: {e}')
        results.append(('Write event capture and publish', False))

    # ── Test 7: Unlink event ──
    print('\n  [Test 7] Create unlink rule → delete partner → verify event...')
    try:
        unlink_rule_id = call('rabbitmq.event.rule', 'create', {
            'name': 'Test Partner Unlink',
            'model_id': partner_model_id,
            'event_type': 'unlink',
            'exchange_name': 'integ_test_exchange',
            'exchange_type': 'topic',
            'routing_key': 'partner.deleted',
            'active': True,
        })
        if isinstance(unlink_rule_id, list):
            unlink_rule_id = unlink_rule_id[0]

        del_partner_id = call('res.partner', 'create', {'name': 'To Be Deleted'})
        if isinstance(del_partner_id, list):
            del_partner_id = del_partner_id[0]

        call('res.partner', 'unlink', [del_partner_id])
        time.sleep(1)

        unlink_log_ids = call('rabbitmq.event.log', 'search', [
            ('model_name', '=', 'res.partner'),
            ('event_type', '=', 'unlink'),
            ('direction', '=', 'outbound'),
        ])
        ok = len(unlink_log_ids) > 0
        if ok:
            trigger_outbound_cron(call)
            log = call('rabbitmq.event.log', 'read', [unlink_log_ids[0]], fields=['state'])
            print(f'    Unlink event state: {log[0]["state"]}')
            ok = log[0]['state'] == 'sent'
        print(f'    {"PASS" if ok else "FAIL"}')
        results.append(('Unlink event capture and publish', ok))
    except Exception as e:
        print(f'    FAIL: {e}')
        results.append(('Unlink event capture and publish', False))

    # ── Test 8: Consumer rule with field mapping (create mode) ──
    print('\n  [Test 8] Consumer rule with field mapping...')
    try:
        consumer_rule_id = call('rabbitmq.consumer.rule', 'create', {
            'name': 'Test Consumer',
            'queue_name': 'test_consume_queue',
            'exchange_name': 'integ_test_consume',
            'routing_key': 'test.consume',
            'target_model': 'res.partner',
            'processing_mode': 'mapping',
            'consumer_action': 'create',
            'prefetch_count': 1,
        })
        if isinstance(consumer_rule_id, list):
            consumer_rule_id = consumer_rule_id[0]

        # Add field mappings (field_type uses 'char' not 'text')
        call('rabbitmq.consumer.field.mapping', 'create', {
            'consumer_rule_id': consumer_rule_id,
            'source_field': 'name',
            'target_field': 'name',
            'field_type': 'char',
            'sequence': 1,
        })
        call('rabbitmq.consumer.field.mapping', 'create', {
            'consumer_rule_id': consumer_rule_id,
            'source_field': 'email',
            'target_field': 'email',
            'field_type': 'char',
            'sequence': 2,
        })

        rule = call('rabbitmq.consumer.rule', 'read', [consumer_rule_id],
                     fields=['name', 'mapping_ids'])
        mapping_count = len(rule[0]['mapping_ids'])
        ok = mapping_count == 2
        print(f'    Created consumer rule id={consumer_rule_id} with {mapping_count} field mappings. '
              f'{"PASS" if ok else "FAIL"}')
        results.append(('Consumer rule with field mapping', ok))
    except Exception as e:
        print(f'    FAIL: {e}')
        results.append(('Consumer rule with field mapping', False))

    return results


def main():
    if len(sys.argv) != 4:
        print(f'Usage: {sys.argv[0]} <odoo_port> <rabbitmq_container> <db_name>')
        sys.exit(1)

    odoo_port = sys.argv[1]
    rabbitmq_container = sys.argv[2]
    db_name = sys.argv[3]

    print(f'\n=== Integration Test: Odoo on port {odoo_port}, DB={db_name} ===\n')
    results = run_tests(odoo_port, rabbitmq_container, db_name)

    # Summary
    print('\n' + '=' * 50)
    print('RESULTS:')
    passed = 0
    failed = 0
    for name, ok in results:
        status = 'PASS' if ok else 'FAIL'
        print(f'  [{status}] {name}')
        if ok:
            passed += 1
        else:
            failed += 1
    print(f'\n  {passed} passed, {failed} failed out of {len(results)} tests')
    print('=' * 50)

    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
