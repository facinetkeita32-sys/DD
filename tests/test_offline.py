"""Real HTTP integration tests with independent server and terminal SQLite DBs."""
import http.cookiejar
import copy
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid


class OfflineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.key = secrets.token_hex(16)
        self.processes = {}
        self.logs = []
        self.urls = {}
        self.server = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.local = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.addCleanup(self.cleanup)
        self.start('server')
        self.start('local')

    def cleanup(self):
        for process in self.processes.values():
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for log in self.logs:
            log.close()
        self.temp.cleanup()

    def start(self, role):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        environment = dict(os.environ, DATABASE_URL='',
                           DB_PATH=os.path.join(self.temp.name, role + '.db'),
                           POS_OFFLINE_MODE='1' if role == 'local' else '',
                           OFFLINE_SYNC_ENABLED='1' if role == 'server' else '',
                           OFFLINE_ALLOW_HTTP='1', OFFLINE_TEST_KEY=self.key,
                           SECRET_KEY=self.key)
        log = open(os.path.join(self.temp.name, role + str(port) + '.log'), 'w', encoding='utf-8')
        self.logs.append(log)
        self.urls[role] = f'http://127.0.0.1:{port}'
        self.processes[role] = subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name('offline_fixture.py')), role, str(port)],
            env=environment, stdout=log, stderr=log, cwd=Path(__file__).resolve().parents[1])
        deadline = time.time() + 20
        while time.time() < deadline:
            if self.processes[role].poll() is not None:
                self.fail('Fixture exited: ' + Path(log.name).read_text(encoding='utf-8'))
            try:
                code, _ = self.call(role, '/api/offline/status')
                if code == 200:
                    return
            except OSError:
                pass
            time.sleep(.1)
        self.fail('Fixture startup timed out: ' + Path(log.name).read_text(encoding='utf-8'))

    def call(self, role, path, body=None, headers=None, method=None):
        request = urllib.request.Request(self.urls[role] + path,
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers=dict({'Content-Type': 'application/json'}, **(headers or {})), method=method)
        opener = self.local if role == 'local' else self.server
        try:
            response = opener.open(request, timeout=20)
        except urllib.error.HTTPError as error:
            response = error
        raw = response.read()
        try:
            return response.status, json.loads(raw)
        except ValueError:
            return response.status, raw.decode(errors='replace')

    def state(self, role, body=None):
        code, data = self.call(role, '/__test', body, {'X-Test-Key': self.key})
        self.assertEqual(200, code, data)
        return data

    def pair(self):
        code, data = self.call('local', '/api/offline/enroll', {
            'server_url': self.urls['server'], 'device_name': 'Test POS',
            'login': 'admin', 'password': 'admin',
        })
        self.assertEqual(200, code, data)
        self.login('admin', 'admin')

    def login(self, login, password, role='local'):
        code, data = self.call(role, '/api/auth/login', {'login': login, 'password': password})
        self.assertEqual(200, code, data)
        return data['data']

    def sale(self, amount=None, method=1):
        product = self.state('local')['products'][0]
        payload = {'lines': [{'product_id': product['id'], 'product_name': 'Test product',
                               'qty': 2, 'price_unit': product['price'], 'discount': 0}],
                   'payments': [{'payment_method_id': method,
                                 'amount': product['price'] * 2 if amount is None else amount}]}
        return self.call('local', '/api/orders', payload)

    def test_offline_restart_lost_ack_and_exactly_once_cash_sale(self):
        self.assertFalse(self.call('local', '/api/offline/status')[1]['data']['ready'])
        self.assertEqual([], self.state('local')['users'])
        self.pair()
        user = self.login('cashier1', '1234')
        self.assertNotIn('password', user)
        self.state('local', {'online': False})
        self.call('local', '/api/auth/logout', {})
        self.login('cashier1', '1234')
        code, result = self.call('local', '/api/sessions', {'cash_register_balance_start': 1000})
        self.assertEqual(200, code, result)
        session_id = result['data']['id']
        self.assertEqual(200, self.call('local', f'/api/sessions/{session_id}/open', {})[0])
        before = self.state('local')['products'][0]
        code, result = self.sale()
        self.assertEqual(200, code, result)
        reference = result['data']['name']
        self.assertTrue(reference.startswith('OFF-'))
        self.assertEqual(3, len(self.state('local')['queue']))
        self.assertEqual([], self.state('server')['orders'])
        # Restart while disconnected, using exactly the same local DB.
        self.processes['local'].terminate()
        self.processes['local'].wait(timeout=5)
        self.start('local')
        self.state('local', {'online': False})
        self.login('cashier1', '1234')
        self.assertEqual(1, len(self.state('local')['orders']))
        self.assertEqual(200, self.call('local', f'/api/sessions/{session_id}/close', {'cash_register_balance_end': 1000})[0])
        self.state('local', {'online': True, 'drop_ack': True, 'sync': True})
        self.assertTrue(any(row['status'] == 'pending' for _, row in self.state('local')['queue']))
        self.state('local', {'sync': True})
        central = self.state('server')
        terminal = self.state('local')
        self.assertEqual(1, len(central['orders']))
        self.assertEqual(reference, central['orders'][0]['name'])
        self.assertEqual(user['id'], central['orders'][0]['user_id'])
        self.assertEqual('closed', central['sessions'][0]['state'])
        self.assertEqual(before['quantity'] - 2, central['products'][0]['quantity'])
        self.assertEqual(central['products'][0]['quantity'], terminal['products'][0]['quantity'])
        self.assertTrue(all(row['status'] == 'sent' for _, row in terminal['queue']))
        self.assertTrue(all(user['password'].startswith('scrypt:') for user in terminal['users']))
        self.state('local', {'sync': True})
        self.assertEqual(1, len(self.state('server')['orders']))

    def test_local_queue_failure_and_non_cash_sales_roll_back(self):
        self.pair()
        before = self.state('local')
        self.state('local', {'capture_error': True})
        self.assertEqual(400, self.sale()[0])
        self.state('local', {'capture_error': False})
        self.assertEqual(400, self.sale(method=2)[0])
        self.assertEqual(400, self.sale(amount=1)[0])
        after = self.state('local')
        self.assertEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])
        self.assertEqual([], after['queue'])
        for path in ('/api/customers', '/api/orders/1/cancel', '/api/backup/restore', '/api/system/init'):
            self.assertEqual(403, self.call('local', path, {})[0], path)

    def test_stock_conflict_and_revocation_never_drop_pending_sales(self):
        self.pair()
        self.assertEqual(200, self.sale()[0])
        product = self.state('local')['products'][0]
        self.state('server', {'product_id': product['id'], 'stock': 0})
        terminal = self.state('local', {'sync': True})
        self.assertEqual('conflict', terminal['client']['error'])
        self.assertEqual('pending', terminal['queue'][0][1]['status'])
        self.assertEqual([], self.state('server')['orders'])
        self.state('server', {'product_id': product['id'], 'stock': 100})
        self.state('local', {'sync': True})
        self.assertEqual(1, len(self.state('server')['orders']))
        self.assertEqual(200, self.sale()[0])
        self.login('admin', 'admin', 'server')
        device = self.state('local')['client']['device_id']
        self.assertEqual(200, self.call('server', f'/api/offline/devices/{device}/revoke', {})[0])
        terminal = self.state('local', {'sync': True})
        self.assertTrue(terminal['client']['blocked'])
        self.assertEqual(1, sum(row['status'] == 'pending' for _, row in terminal['queue']))
        self.assertEqual(401, self.sale()[0])

    def test_first_login_expiry_and_passwords_are_device_scoped(self):
        code, _ = self.call('server', '/api/offline/register', {
            'login': 'cashier1', 'password': '1234', 'device_name': 'Not authorized',
        })
        self.assertEqual(403, code)
        self.pair()
        user = self.login('cashier1', '1234')
        self.state('local', {'online': False})
        self.call('local', '/api/auth/logout', {})
        self.assertEqual(401, self.call('local', '/api/auth/login', {'login': 'cashier2', 'password': '5678'})[0])
        self.login('cashier1', '1234')
        self.state('local', {'expire': user['id']})
        self.assertEqual(401, self.call('local', '/api/auth/login', {'login': 'cashier1', 'password': '1234'})[0])
        self.state('local', {'online': True})
        self.login('cashier1', '1234')
        credentials = self.state('local')['client']
        headers = {'Authorization': 'Bearer ' + credentials['credential'],
                   'X-POS-Server': credentials['server_id'], 'X-POS-Epoch': credentials['epoch']}
        _, catalogue = self.call('server', '/api/offline/catalogue', headers=headers)
        self.assertNotIn('res.users', catalogue['data']['tables'])
        self.assertNotIn('pos.order', catalogue['data']['tables'])
        self.assertNotIn('password', json.dumps(catalogue))
        self.assertNotIn('cost_price', json.dumps(catalogue))

    def test_server_restore_requires_reconciliation_and_preserves_local_queue(self):
        self.pair()
        self.assertEqual(200, self.sale()[0])
        old_epoch = self.state('server')['identity']['epoch']
        self.state('server', {'restore': True})
        self.assertNotEqual(old_epoch, self.state('server')['identity']['epoch'])
        terminal = self.state('local', {'sync': True})
        self.assertTrue(terminal['client']['blocked'])
        self.assertEqual('epoch', terminal['client']['error'])
        self.assertEqual('pending', terminal['queue'][0][1]['status'])
        self.assertEqual(1, len(terminal['orders']))

    def test_existing_business_database_and_local_origin_are_protected(self):
        before = self.state('server')
        environment = dict(os.environ, DATABASE_URL='',
                           DB_PATH=os.path.join(self.temp.name, 'server.db'),
                           POS_OFFLINE_MODE='1', OFFLINE_SYNC_ENABLED='')
        result = subprocess.run([sys.executable, '-c', 'from pos_system.main import app'],
                                cwd=Path(__file__).resolve().parents[1], env=environment,
                                capture_output=True, text=True, timeout=20)
        self.assertNotEqual(0, result.returncode)
        self.assertIn('Refusing to provision over an existing business database', result.stderr)
        self.assertEqual(before['products'], self.state('server')['products'])
        self.assertEqual(before['users'], self.state('server')['users'])
        self.assertEqual(401, self.call('local', '/api/products')[0])
        self.assertEqual(403, self.call('local', '/api/offline/status',
                                       headers={'Origin': 'https://other.example'})[0])

    def test_manager_product_create_sale_id_collisions_and_restart(self):
        self.pair()
        self.login('manager1', 'manager123')
        permissions = self.call('local', '/api/auth/permissions')[1]['data']
        self.assertIn('products', permissions['screens'])
        self.assertIn('product.create', permissions['actions'])
        self.assertNotIn('settings.write', permissions['actions'])
        self.state('local', {'online': False})
        code, category = self.call('local', '/api/product-categories', {'name': 'Offline manager category'})
        self.assertEqual(200, code, category)
        category = category['data']
        code, result = self.call('local', '/api/products', {
            'name': 'Offline manager product', 'barcode': 'OFFLINE-NEW', 'list_price': 1234,
            'cost_price': 500, 'available_qty': 10, 'categ_id': category['id'], 'pos_categ_ids': [],
        })
        self.assertEqual(200, code, result)
        local_id = result['data']['id']
        self.login('admin', 'admin', 'server')
        remote_category = self.call('server', '/api/product-categories', {'name': 'Concurrent server category'})[1]['data']
        remote_product = self.call('server', '/api/products', {
            'name': 'Concurrent server product', 'barcode': 'CENTRAL-OTHER',
            'list_price': 999, 'available_qty': 44,
        })[1]['data']
        self.assertEqual(local_id, remote_product['id'])
        self.assertEqual(category['id'], remote_category['id'])
        code, sale = self.call('local', '/api/orders', {
            'lines': [{'product_id': local_id, 'product_name': 'Offline manager product',
                       'qty': 2, 'price_unit': 1234, 'discount': 0}],
            'payments': [{'payment_method_id': 1, 'amount': 2468}],
        })
        self.assertEqual(200, code, sale)
        self.assertEqual(200, self.call('local', f'/api/products/{local_id}', {
            'list_price': 1500, 'available_qty': 12,
        }, method='PUT')[0])
        terminal = self.state('local', {'online': True, 'sync': True})
        self.assertIsNone(terminal['client'].get('error'), terminal['client'])
        self.assertTrue(all(row['status'] == 'sent' for _, row in terminal['queue']))
        central = self.call('server', '/api/products')[1]['data']
        created = next(row for row in central if row['name'] == 'Offline manager product')
        untouched = next(row for row in central if row['name'] == 'Concurrent server product')
        self.assertNotEqual(created['id'], local_id)
        self.assertEqual(44, untouched['available_qty'])
        self.assertEqual(12, created['available_qty'])
        self.assertEqual(1500, created['list_price'])
        orders = self.call('server', '/api/orders')[1]['data']
        self.assertEqual(created['id'], orders[0]['lines'][0]['product_id']['id'])
        self.assertEqual(2468, orders[0]['amount_total'])
        local = self.call('local', '/api/products')[1]['data']
        self.assertEqual(local_id, next(row for row in local if row['name'] == 'Offline manager product')['id'])
        self.assertNotEqual(local_id, next(row for row in local if row['name'] == 'Concurrent server product')['id'])
        self.processes['local'].terminate()
        self.processes['local'].wait(timeout=5)
        self.start('local')
        self.login('manager1', 'manager123')
        product = self.call('local', f'/api/products/{local_id}')[1]['data']
        self.assertEqual('Offline manager product', product['name'])
        self.assertEqual(category['id'], product['categ_id']['id'])

    def test_admin_settings_delivery_and_manager_settings_restrictions(self):
        self.pair()
        self.login('manager1', 'manager123')
        self.state('local', {'online': False})
        self.assertEqual(403, self.call('local', '/api/config', {'low_stock_threshold': 3}, method='PUT')[0])
        self.assertEqual(403, self.call('local', '/api/company', {'name': 'Not permitted'}, method='PUT')[0])
        self.login('admin', 'admin')
        permissions = self.call('local', '/api/auth/permissions')[1]['data']
        self.assertIn('settings', permissions['screens'])
        self.assertIn('settings.write', permissions['actions'])
        self.assertEqual(200, self.call('local', '/api/company', {'name': 'Offline company'}, method='PUT')[0])
        self.assertEqual(200, self.call('local', '/api/config', {
            'low_stock_threshold': 0, 'receipt_footer': 'Offline footer',
        }, method='PUT')[0])
        zone = self.call('local', '/api/delivery-zones', {'name': 'Offline delivery', 'cost': 777})[1]['data']
        self.login('admin', 'admin', 'server')
        self.call('server', '/api/delivery-zones', {'name': 'Concurrent delivery', 'cost': 888})
        self.call('server', '/api/config', {'receipt_header': 'Unrelated remote header'}, method='PUT')
        product = self.state('local')['products'][0]
        total = product['price'] + 777
        self.assertEqual(200, self.call('local', '/api/orders', {
            'lines': [{'product_id': product['id'], 'qty': 1, 'price_unit': product['price'], 'discount': 0}],
            'payments': [{'payment_method_id': 1, 'amount': total}],
            'delivery_zone_id': zone['id'], 'delivery_cost': 777,
        })[0])
        terminal = self.state('local', {'online': True, 'sync': True})
        self.assertIsNone(terminal['client'].get('error'), terminal['client'])
        config = self.call('server', '/api/config')[1]['data']
        self.assertEqual(0, config['low_stock_threshold'])
        self.assertEqual('Offline footer', config['receipt_footer'])
        self.assertEqual('Unrelated remote header', config['receipt_header'])
        self.assertEqual('Offline company', self.call('server', '/api/company')[1]['data']['name'])
        zones = self.call('server', '/api/delivery-zones')[1]['data']
        new_zone = next(row for row in zones if row['name'] == 'Offline delivery')
        order = self.call('server', '/api/orders')[1]['data'][0]
        self.assertEqual(new_zone['id'], order['delivery_zone_id']['id'])
        self.assertEqual(total, order['amount_total'])

    def test_product_conflict_requires_manager_review_and_preserves_dependent_sale(self):
        self.pair()
        self.login('cashier1', '1234')
        self.login('manager1', 'manager123')
        self.state('local', {'online': False})
        product = self.state('local')['products'][0]
        pid = product['id']
        self.assertEqual(200, self.call('local', f'/api/products/{pid}', {
            'name': 'Local choice', 'list_price': product['price'] + 100,
        }, method='PUT')[0])
        self.assertEqual(200, self.sale()[0])
        self.login('admin', 'admin', 'server')
        self.call('server', f'/api/products/{pid}', {'name': 'Server choice', 'list_price': product['price'] + 200}, method='PUT')
        terminal = self.state('local', {'online': True, 'sync': True})
        self.assertEqual('catalog_conflict', terminal['client']['error'])
        conflicts = self.call('local', '/api/offline/conflicts')[1]['data']
        self.assertEqual(1, len(conflicts))
        conflict_id = conflicts[0]['id']
        self.assertEqual('Server choice', conflicts[0]['current']['name'])
        self.assertEqual([], self.state('server')['orders'])
        self.login('cashier1', '1234')
        self.assertEqual([], self.call('local', '/api/offline/conflicts')[1]['data'])
        self.assertEqual(403, self.call('local', f'/api/offline/conflicts/{conflict_id}/resolve', {'decision': 'retry'})[0])
        self.assertEqual(403, self.call('local', '/api/products', {'name': 'Forbidden', 'list_price': 1})[0])
        self.login('manager1', 'manager123')
        self.assertEqual(200, self.call('local', f'/api/offline/conflicts/{conflict_id}/resolve', {'decision': 'retry'})[0])
        terminal = self.state('local', {'sync': True})
        self.assertIsNone(terminal['client'].get('error'), terminal['client'])
        self.assertEqual('Local choice', self.call('server', f'/api/products/{pid}')[1]['data']['name'])
        self.assertEqual(1, len(self.state('server')['orders']))
        self.assertTrue(all(row['status'] in ('sent', 'superseded') for _, row in terminal['queue']))

    def test_duplicate_barcode_create_can_be_reviewed_without_losing_sale(self):
        self.pair()
        product = self.call('local', '/api/products')[1]['data'][0]
        self.state('local', {'online': False})
        code, result = self.call('local', '/api/products', {
            'name': 'Duplicate barcode trial', 'barcode': product['barcode'],
            'list_price': 555, 'available_qty': 10,
        })
        self.assertEqual(200, code, result)
        local_id = result['data']['id']
        self.assertEqual(200, self.call('local', '/api/orders', {
            'lines': [{'product_id': local_id, 'qty': 1, 'price_unit': 555, 'discount': 0}],
            'payments': [{'payment_method_id': 1, 'amount': 555}],
        })[0])
        terminal = self.state('local', {'online': True, 'sync': True})
        self.assertEqual('catalog_conflict', terminal['client']['error'])
        conflict = self.call('local', '/api/offline/conflicts')[1]['data'][0]
        self.assertEqual(400, self.call('local', f'/api/offline/conflicts/{conflict["id"]}/resolve', {'decision': 'discard'})[0])
        self.assertEqual(200, self.call('local', f'/api/offline/conflicts/{conflict["id"]}/resolve', {
            'decision': 'retry', 'values': {'barcode': 'OFFUNIQUE555'},
        })[0])
        terminal = self.state('local', {'sync': True})
        self.assertIsNone(terminal['client'].get('error'), terminal['client'])
        self.assertEqual(1, len(self.state('server')['orders']))
        products = self.call('server', '/api/products')[1]['data']
        created = [row for row in products if row['barcode'] == 'OFFUNIQUE555']
        self.assertEqual(1, len(created), [(p['id'], p['name'], p.get('barcode')) for p in products])
        self.assertEqual(9, created[0]['available_qty'])

    def test_catalogue_queue_failure_rolls_back_and_stale_form_is_rejected(self):
        self.pair()
        self.state('local', {'online': False, 'capture_error': True})
        before = self.state('local')
        code, result = self.call('local', '/api/products', {'name': 'Should roll back', 'list_price': 555})
        self.assertEqual(400, code, result)
        self.assertEqual(before['products'], self.state('local')['products'])
        self.assertEqual([], self.state('local')['queue'])
        self.state('local', {'capture_error': False})
        product = self.call('local', '/api/products')[1]['data'][0]
        self.call('local', f'/api/products/{product["id"]}', {'name': 'Newer local revision'}, method='PUT')
        self.assertEqual(409, self.call('local', f'/api/products/{product["id"]}', {
            'list_price': 999, 'offline_revision': product['offline_revision'],
        }, method='PUT')[0])

    def test_stock_adjustments_preserve_concurrent_central_sales(self):
        self.pair()
        self.login('manager1', 'manager123')
        self.state('local', {'online': False})
        product = self.state('local')['products'][0]
        self.assertEqual(200, self.call('local', f'/api/products/{product["id"]}', {
            'available_qty': product['quantity'] + 5,
        }, method='PUT')[0])
        self.login('admin', 'admin', 'server')
        self.assertEqual(200, self.call('server', '/api/orders', {
            'lines': [{'product_id': product['id'], 'qty': 2, 'price_unit': product['price'], 'discount': 0}],
            'payments': [{'payment_method_id': 1, 'amount': product['price'] * 2}],
        })[0])
        terminal = self.state('local', {'online': True, 'sync': True})
        self.assertIsNone(terminal['client'].get('error'), terminal['client'])
        central = self.call('server', f'/api/products/{product["id"]}')[1]['data']
        self.assertEqual(product['quantity'] + 5 - 2, central['available_qty'])

    def test_server_rechecks_roles_for_forged_catalogue_events_and_cost_reads(self):
        self.pair()
        cashier = self.login('cashier1', '1234')
        self.assertTrue(all('cost_price' not in row for row in self.call('local', '/api/products')[1]['data']))
        manager = self.login('manager1', 'manager123')
        self.state('local', {'online': False})
        self.assertEqual(200, self.call('local', '/api/products', {
            'name': 'Authorized manager product', 'list_price': 100,
        })[0])
        local = self.state('local')
        operation = local['queue'][0][1]['operation']
        grants = dict(local['grants'])
        settings = local['client']
        headers = {'Authorization': 'Bearer ' + settings['credential'],
                   'X-POS-Server': settings['server_id'], 'X-POS-Epoch': settings['epoch']}
        forged = copy.deepcopy(operation)
        forged['id'] = str(uuid.uuid4())
        forged['grant'] = {key: grants[str(cashier['id'])][key] for key in ('id', 'token')}
        self.assertEqual(403, self.call('server', '/api/offline/push', {'operation': forged}, headers=headers)[0])
        forged['id'] = str(uuid.uuid4())
        forged['grant'] = {key: grants[str(manager['id'])][key] for key in ('id', 'token')}
        forged['data'].update(model='res.company', action='update', record={'id': 1},
                              values={'name': 'Forbidden setting'}, base={'name': 'My Company'})
        self.assertEqual(403, self.call('server', '/api/offline/push', {'operation': forged}, headers=headers)[0])
        cashier_headers = dict(headers, **{'X-POS-User-Grant': grants[str(cashier['id'])]['id'],
                                           'X-POS-User-Token': grants[str(cashier['id'])]['token']})
        snapshot = self.call('server', '/api/offline/catalogue', headers=cashier_headers)[1]['data']
        self.assertTrue(all('cost_price' not in row for row in snapshot['tables']['product.product']))
        self.assertEqual(10, len(self.call('server', '/api/products')[1]['data']))

    def test_offline_receipt_stays_authenticated_local_and_read_only(self):
        self.pair()
        self.state('local', {'online': False})
        code, sale = self.sale()
        self.assertEqual(200, code, sale)
        order_id = sale['data']['id']
        before = self.state('local')
        # An external browser does not inherit the desktop WebView cookie jar.
        with self.assertRaises(urllib.error.HTTPError) as missing_session:
            urllib.request.urlopen(self.urls['local'] + f'/api/receipt/{order_id}/html')
        self.assertEqual(401, missing_session.exception.code)
        code, html = self.call('local', f'/api/receipt/{order_id}/html?lang=fr')
        self.assertEqual(200, code)
        self.assertIn('<html lang="fr">', html)
        self.assertIn('REÇU', html)
        self.assertIn(sale['data']['name'], html)
        request = urllib.request.Request(self.urls['local'] + f'/api/receipt/{order_id}/pdf?lang=fr')
        with self.local.open(request, timeout=10) as response:
            self.assertEqual('application/pdf', response.headers.get_content_type())
            self.assertTrue(response.read().startswith(b'%PDF'))
        after = self.state('local')
        self.assertEqual(before['orders'], after['orders'])
        self.assertEqual(before['products'], after['products'])
        self.assertEqual(before['queue'], after['queue'])

    def test_receipt_html_escapes_names_before_embedding(self):
        self.pair()
        self.state('local', {'online': False})
        _, sale = self.sale()
        product_id = self.state('local')['products'][0]['id']
        malicious = '<img src=x onerror="window.parent.receiptInjected=true">'
        self.assertEqual(200, self.call('local', f'/api/products/{product_id}', {'name': malicious}, method='PUT')[0])
        self.assertEqual(200, self.call('local', '/api/company', {'name': '<script>bad()</script>'}, method='PUT')[0])
        code, html = self.call('local', f'/api/receipt/{sale["data"]["id"]}/html')
        self.assertEqual(200, code)
        self.assertNotIn(malicious, html)
        self.assertNotIn('<script>bad()</script>', html)
        self.assertIn('&lt;img', html)
        self.assertIn('&lt;script&gt;bad()', html)


if __name__ == '__main__':
    unittest.main()
