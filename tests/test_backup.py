"""Integration tests use an isolated SQLite database, never the installed POS data."""
import base64
import copy
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch


class BackupIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.environment = patch.dict(os.environ, {
            'DATABASE_URL': '', 'DB_PATH': os.path.join(cls.temp.name, 'test.db'),
            'POS_OFFLINE_MODE': '', 'OFFLINE_SYNC_ENABLED': '',
        })
        cls.environment.start()
        from pos_system.main import app
        from pos_system import db, odoo_orm
        from pos_system.services import backup_service
        cls.app, cls.db, cls.orm, cls.service = app, db, odoo_orm, backup_service
        cls.app.config['TESTING'] = True
        from pos_system.models.product_product import ProductProduct
        from pos_system.models.res_partner import ResPartner
        from pos_system.models.res_company import ResCompany
        from pos_system.models.login_log import LoginLog
        from pos_system.models.pos_config import PosConfig
        from pos_system.models.pos_tax import PosTax
        from pos_system.models.pos_category import PosCategory
        from pos_system.models.pos_payment_method import PosPaymentMethod
        from pos_system.models.pos_session import PosSession
        from pos_system.models.pos_order import PosOrder
        from pos_system.models.pos_order_line import PosOrderLine
        from pos_system.models.pos_payment import PosPayment

        cls.image = base64.b64encode(
            b'\x89PNG\r\n\x1a\n' + bytes(range(256)) * 1024).decode('ascii')
        cls.product = ProductProduct.search([])[0]
        cls.product.write({'image': cls.image, 'description': 'Restauré — 商品'})
        cls.customer = ResPartner.search([])[0]
        cls.customer.write({'image': cls.image})
        ResCompany.search([])[0].write({'logo': cls.image})
        tax = PosTax.search([])[0]
        category = PosCategory.search([])[0]
        method = PosPaymentMethod.search([])[0]
        cls.product.write({'tax_ids': [tax.id], 'pos_categ_ids': [category.id]})
        PosConfig.search([])[0].write({
            'category_ids': [category.id], 'payment_method_ids': [method.id],
        })
        session = PosSession.create({'name': 'Backup session', 'user_id': 1, 'state': 'opened'})
        order = PosOrder.create({
            'name': 'BACKUP-001', 'user_id': 1, 'session_id': session.id,
            'partner_id': cls.customer.id, 'amount_total': 150, 'amount_paid': 150, 'state': 'paid',
        })
        PosOrderLine.create({
            'order_id': order.id, 'product_id': cls.product.id, 'qty': 2,
            'price_unit': 75, 'price_subtotal': 150, 'tax_ids': [tax.id],
        })
        PosPayment.create({'order_id': order.id, 'payment_method_id': method.id, 'amount': 150})
        LoginLog.create({'user_id': 1, 'action': 'backup-test', 'details': 'Must survive restore'})
        result = cls.service.save_backup_settings({
            'url': 'https://example.test/backup', 'api_key': 'saved-test-key',
            'interval_minutes': 90, 'auto_backup': False,
        })
        assert result['success'], result
        # Go through JSON, just like an actual downloaded file.
        cls.baseline = json.loads(json.dumps(cls.service.export_full_backup()))

    @classmethod
    def tearDownClass(cls):
        cls.service.stop_auto_backup()
        cls.environment.stop()
        cls.temp.cleanup()

    def setUp(self):
        result = self.service.restore_from_data(None, copy.deepcopy(self.baseline))
        self.assertTrue(result['success'], result)

    def snapshot(self):
        tables = self.service.export_full_backup()['tables']
        return {name: sorted(json.dumps(row, sort_keys=True) for row in rows)
                for name, rows in tables.items()}

    def login_client(self):
        client = self.app.test_client()
        user = next(row for row in self.baseline['tables']['res.users'] if row['id'] == 1)
        response = client.post('/api/auth/login', json={
            'login': user['login'], 'password': user['password'],
        })
        self.assertEqual(200, response.status_code)
        return client

    def test_full_round_trip_replaces_all_tables_and_survives_cache_reload(self):
        expected = self.snapshot()
        conn = self.db.get_conn()
        try:
            for table in self.baseline['tables']:
                conn.execute('DELETE FROM ' + self.service._quote(table))
            conn.commit()
        finally:
            conn.close()
        self.orm._db_cache.clear()
        self.orm._load_cache()
        result = self.service.restore_from_data(None, copy.deepcopy(self.baseline))
        self.assertTrue(result['success'], result)
        self.assertEqual(expected, self.snapshot())
        # Simulate a process restart: no cached records may be needed for recovery.
        self.orm._db_cache.clear()
        self.orm._load_cache()
        self.service.load_backup_settings()
        self.assertEqual(expected, self.snapshot())
        from pos_system.models.product_product import ProductProduct
        from pos_system.models.pos_config import PosConfig
        product = ProductProduct.browse(self.product.id)[0]
        self.assertEqual(self.image, product._data['image'])
        self.assertTrue(product.read()['tax_ids'])
        self.assertTrue(product.read()['pos_categ_ids'])
        self.assertTrue(PosConfig.search([])[0].read()['payment_method_ids'])
        self.assertEqual('saved-test-key', self.service._backup_settings['api_key'])
        new = ProductProduct.create({'name': 'New item after restore', 'list_price': 15})
        self.assertGreater(new.id, max(row['id'] for row in self.baseline['tables']['product.product']))

    def test_database_error_rolls_back_every_table_and_leaves_cache_unchanged(self):
        before = self.snapshot()
        cache = copy.deepcopy(self.orm._db_cache)
        damaged = copy.deepcopy(self.baseline)
        # SQL NOT NULL failure occurs after deletion and earlier inserts.
        damaged['tables']['res.users'][0]['login'] = None
        result = self.service.restore_from_data(None, damaged)
        self.assertFalse(result['success'])
        self.assertIn('no data was changed', result['error'])
        self.assertEqual(before, self.snapshot())
        self.assertEqual(cache, self.orm._db_cache)

    def test_rejects_malformed_incomplete_and_unsupported_backups_without_changes(self):
        before = self.snapshot()
        bad_files = [None, [], {}, {'version': '99.0'}]
        for mutation in ('missing_table', 'unknown_table', 'duplicate_id', 'missing_column', 'bad_settings'):
            damaged = copy.deepcopy(self.baseline)
            if mutation == 'missing_table':
                del damaged['tables']['res.users']
            elif mutation == 'unknown_table':
                damaged['tables']['injected; DROP TABLE users'] = []
            elif mutation == 'duplicate_id':
                damaged['tables']['res.users'].append(damaged['tables']['res.users'][0])
            elif mutation == 'missing_column':
                del damaged['tables']['product.product'][0]['image']
            else:
                damaged['tables']['backup.settings'][0]['interval_minutes'] = 0
            bad_files.append(damaged)
        for data in bad_files:
            with self.subTest(data_type=type(data).__name__):
                result = self.service.restore_from_data(None, data)
                self.assertFalse(result['success'], result)
                self.assertEqual(before, self.snapshot())

    def test_legacy_backup_restores_images_and_reports_missing_information(self):
        legacy = {'version': '2.0'}
        for key, table in self.service.LEGACY_TABLES.items():
            if key not in ('logs', 'languages'):
                legacy[key] = copy.deepcopy(self.baseline['tables'][table])
        result = self.service.restore_from_data(None, {'success': True, 'data': legacy})
        self.assertTrue(result['success'], result)
        self.assertTrue(result['warnings'])
        from pos_system.models.product_product import ProductProduct
        self.assertEqual(self.image, ProductProduct.browse(self.product.id)[0]._data['image'])
        self.assertEqual([], ProductProduct.browse(self.product.id)[0].read()['tax_ids'])
        self.assertEqual(self.baseline['tables']['login.log'],
                         self.service.export_full_backup()['tables']['login.log'])

    def test_download_and_restore_endpoints_and_session_reset(self):
        client = self.login_client()
        response = client.get('/api/backup/download')
        self.assertEqual(200, response.status_code)
        data = response.get_json()
        product = next(row for row in data['tables']['product.product'] if row['id'] == self.product.id)
        self.assertEqual(self.image, product['image'])
        self.assertIn('attachment', response.headers['Content-Disposition'])
        exported = client.get('/api/backup/export').get_json()
        self.assertEqual(data['tables'], exported['data']['tables'])
        failure = client.post('/api/backup/restore', json={'data': {'version': '99.0'}})
        self.assertEqual(400, failure.status_code)
        with client.session_transaction() as session:
            self.assertEqual(1, session.get('user_id'))
        response = client.post('/api/backup/restore', json={'data': data})
        self.assertEqual(200, response.status_code)
        self.assertTrue(response.get_json()['success'])
        with client.session_transaction() as session:
            self.assertNotIn('user_id', session)
        self.assertEqual(401, client.get('/api/backup/export').status_code)

    def test_restore_invalidates_other_browsers_and_allows_fresh_login(self):
        restoring_client = self.login_client()
        other_client = self.login_client()
        failure = restoring_client.post('/api/backup/restore', json={
            'data': {'version': '99.0'},
        })
        self.assertEqual(400, failure.status_code)
        self.assertEqual(200, other_client.get('/api/auth/me').status_code)
        restored = copy.deepcopy(self.baseline)
        user = next(row for row in restored['tables']['res.users'] if row['id'] == 1)
        user['password'] = 'restored-password'
        response = restoring_client.post('/api/backup/restore', json={'data': restored})
        self.assertEqual(200, response.status_code)
        for client in (restoring_client, other_client):
            self.assertEqual(401, client.get('/api/auth/me').status_code)
            self.assertEqual(401, client.get('/api/backup/export').status_code)
        self.assertEqual(401, other_client.post('/api/auth/login', json={
            'login': user['login'], 'password': 'admin',
        }).status_code)
        self.assertEqual(200, other_client.post('/api/auth/login', json={
            'login': user['login'], 'password': user['password'],
        }).status_code)
        self.assertEqual(200, other_client.get('/api/auth/me').status_code)

    def test_service_restore_also_invalidates_sessions(self):
        client = self.login_client()
        result = self.service.restore_from_data(None, copy.deepcopy(self.baseline))
        self.assertTrue(result['success'], result)
        self.assertEqual(401, client.get('/api/auth/me').status_code)

    def test_remote_upload_does_not_block_other_api_requests(self):
        uploading_client = self.login_client()
        other_client = self.login_client()
        upload_started = threading.Event()
        finish_upload = threading.Event()
        uploaded = []

        def stalled_upload(request, timeout):
            uploaded.append(json.loads(request.data))
            upload_started.set()
            if not finish_upload.wait(10):
                raise TimeoutError('Test upload was not released')
            return response

        with patch.object(self.service.urllib.request, 'urlopen') as urlopen:
            response = urlopen.return_value
            response.__enter__.return_value.read.return_value = b'ok'
            urlopen.side_effect = stalled_upload
            with ThreadPoolExecutor(max_workers=2) as executor:
                upload = executor.submit(uploading_client.post, '/api/backup/push', json={
                    'url': 'https://example.test/backup', 'api_key': 'test-key',
                })
                try:
                    self.assertTrue(upload_started.wait(5), 'Upload never started')
                    other_request = executor.submit(other_client.get, '/api/auth/me')
                    self.assertEqual(200, other_request.result(timeout=3).status_code)
                    self.assertFalse(upload.done())
                    self.assertEqual(self.baseline['tables']['product.product'],
                                     uploaded[0]['tables']['product.product'])
                finally:
                    finish_upload.set()
                result = upload.result(timeout=5)
                self.assertEqual(200, result.status_code)
                self.assertTrue(result.get_json()['success'])
        self.assertEqual(200, uploading_client.get('/api/auth/me').status_code)

    def test_auto_backup_settings_persist_and_worker_is_replaced(self):
        values = {'url': 'https://example.test/backup', 'api_key': 'key',
                  'interval_minutes': 60, 'auto_backup': True}
        self.assertTrue(self.service.save_backup_settings(values)['success'])
        old_stop = self.service._auto_backup_stop
        self.assertTrue(self.service.get_backup_status()['auto_backup_running'])
        backup = self.service.export_full_backup()
        self.assertTrue(self.service.restore_from_data(None, backup)['success'])
        self.assertTrue(old_stop.is_set())
        self.assertIsNot(old_stop, self.service._auto_backup_stop)
        self.assertTrue(self.service.get_backup_status()['auto_backup_running'])
        self.service.stop_auto_backup()
        self.orm._db_cache.clear()
        self.orm._load_cache()
        self.service.load_backup_settings()
        self.assertTrue(self.service.get_backup_status()['auto_backup_running'])


if __name__ == '__main__':
    unittest.main()
