"""Run dashboard integration scenarios in a fresh process and temporary SQLite DB.

The application initializes its ORM at import time. A subprocess prevents the
backup suite's global ORM connection settings from leaking into these scenarios.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DashboardScenarios:
    @classmethod
    def setUpClass(cls):
        from pos_system.main import app
        from pos_system.services import backup_service
        from pos_system.models.res_users import ResUsers
        from pos_system.models.pos_order import PosOrder
        from pos_system.models.pos_order_line import PosOrderLine
        from pos_system.models.product_product import ProductProduct
        cls.app = app
        app.config['TESTING'] = True
        cls.backup = backup_service
        cls.admin = ResUsers.search([('role', '=', 'admin')])[0]
        cls.cashier = ResUsers.search([('role', '=', 'cashier')])[0]
        cls.manager = ResUsers.create({'name': 'Manager', 'login': 'manager-test',
                                      'password': 'test', 'role': 'manager'})
        cls.other = ResUsers.create({'name': 'Other cashier', 'login': 'other-test',
                                    'password': 'test', 'role': 'cashier'})
        cls.denied = ResUsers.create({'name': 'Unknown', 'login': 'unknown-test',
                                     'password': 'test', 'role': 'unknown'})
        products = ProductProduct.search([])
        cls.product = products[0]
        cls.orders = []

        def order(name, day, amount, state, user=None, paid=None, company=None):
            record = PosOrder.create({
                'name': name, 'date_order': day + ' 12:00:00',
                'user_id': (user or cls.cashier).id, 'state': state,
                'amount_total': amount, 'amount_paid': amount if paid is None else paid,
                'company_id': company,
            })
            cls.orders.append(record)
            return record

        first = order('CURRENT-A', '2026-01-10', 100.25, 'paid')
        second = order('CURRENT-B', '2026-01-11', 200.5, 'done')
        other = order('PRIVATE-OTHER', '2026-01-10', 400.75, 'paid', cls.other)
        order('PENDING', '2026-01-11', 80, 'pending', paid=20)
        order('CANCELLED', '2026-01-11', 999, 'cancelled')
        order('REFUNDED', '2026-01-11', 55, 'refunded')
        draft = order('DRAFT', '2026-01-11', 77, 'draft')
        order('PREVIOUS-A', '2026-01-08', 50, 'paid')
        order('PREVIOUS-B', '2026-01-09', 100, 'paid')
        order('OUTSIDE-DATE', '2026-01-12', 9999, 'paid')
        order('FOREIGN-COMPANY', '2026-01-10', 99999, 'paid', company=999)
        for record, product, amount in [(first, products[0], 90.25),
                                        (second, products[0], 200.5),
                                        (other, products[1], 400.75),
                                        (draft, products[1], 77777)]:
            PosOrderLine.create({'order_id': record.id, 'product_id': product.id,
                                 'qty': 1, 'price_unit': amount, 'price_subtotal': amount})
        cls.baseline = backup_service.export_full_backup()

    def setUp(self):
        self.assertTrue(self.backup.restore_from_data(None, copy.deepcopy(self.baseline))['success'])

    def client(self, user=None):
        user = user or self.admin
        client = self.app.test_client()
        response = client.post('/api/auth/login', json={
            'login': user._data['login'], 'password': user._data['password'],
        })
        self.assertEqual(200, response.status_code)
        return client

    def query(self, client):
        return client.get('/api/dashboard/analytics?period=custom&date_from=2026-01-10&date_to=2026-01-11')

    def test_paid_totals_boundaries_previous_period_and_no_writes(self):
        client = self.client()
        before = self.backup.export_full_backup()
        response = self.query(client)
        self.assertEqual(200, response.status_code)
        self.assertEqual('no-store', response.headers['Cache-Control'])
        data = response.get_json()['data']
        self.assertEqual(701.5, data['summary']['revenue'])
        self.assertEqual(3, data['summary']['orders'])
        self.assertEqual(60, data['summary']['outstanding'])
        self.assertAlmostEqual(701.5 / 3, data['summary']['average_order'])
        self.assertEqual(150, data['comparison']['revenue']['value'])
        self.assertEqual('2026-01-08', data['previous_from'])
        self.assertEqual('2026-01-09', data['previous_to'])
        self.assertEqual([501, 200.5], [row['revenue'] for row in data['series']])
        self.assertEqual(701.5, sum(row['revenue'] for row in data['series']))
        self.assertEqual([400.75, 290.75], [row['revenue'] for row in data['top_products']])
        self.assertEqual(6, data['matching_orders'])
        self.assertIn('inventory_value', data['stock'])
        after = self.backup.export_full_backup()
        self.assertEqual(before['tables'], after['tables'])
        self.assertEqual(before['sequences'], after['sequences'])

    def test_cashier_scope_no_other_sales_costs_or_customer_data(self):
        response = self.query(self.client(self.cashier))
        data = response.get_json()['data']
        self.assertEqual('personal', data['scope'])
        self.assertEqual(300.75, data['summary']['revenue'])
        self.assertEqual(2, data['summary']['orders'])
        self.assertEqual(1, len(data['top_products']))
        self.assertIsNone(data['stock'])
        self.assertNotIn('PRIVATE-OTHER', response.get_data(as_text=True))
        for key in ('password', 'email', 'phone', 'partner_id', 'cost_price', 'inventory_value'):
            self.assertNotIn('"' + key + '"', response.get_data(as_text=True))

    def test_manager_has_business_totals_but_not_inventory_cost(self):
        data = self.query(self.client(self.manager)).get_json()['data']
        self.assertEqual('business', data['scope'])
        self.assertEqual(701.5, data['summary']['revenue'])
        self.assertNotIn('inventory_value', data['stock'])

    def test_authentication_and_unsupported_client_scopes(self):
        self.assertEqual(401, self.query(self.app.test_client()).status_code)
        self.assertEqual(403, self.query(self.client(self.denied)).status_code)
        client = self.client(self.cashier)
        for arg in ('user_id=1', 'company_id=1', 'store_id=1', 'role=admin'):
            self.assertEqual(400, client.get('/api/dashboard/analytics?' + arg).status_code)
        legacy = client.get('/api/dashboard')
        self.assertEqual(200, legacy.status_code)
        self.assertIn('today_sales', legacy.get_json()['data'])

    def test_invalid_dates_and_empty_periods(self):
        client = self.client()
        for query in ('period=bad', 'period=custom',
                      'period=custom&date_from=2026-01-12&date_to=2026-01-10',
                      'period=custom&date_from=2020-01-01&date_to=2026-01-10',
                      'period=custom&date_from=9999-01-01&date_to=9999-01-02',
                      'period=custom&date_from=0001-01-01&date_to=0001-01-02'):
            self.assertEqual(400, client.get('/api/dashboard/analytics?' + query).status_code, query)
        data = client.get('/api/dashboard/analytics?period=custom&date_from=2025-01-01&date_to=2025-01-03').get_json()['data']
        self.assertEqual(0, data['summary']['revenue'])
        self.assertEqual(3, len(data['series']))
        self.assertEqual([], data['recent_orders'])
        self.assertIsNone(data['comparison']['revenue']['change_percent'])

    def test_ambiguous_companies_fail_closed(self):
        from pos_system.models.res_company import ResCompany
        ResCompany.create({'name': 'Other store'})
        response = self.query(self.client())
        self.assertEqual(409, response.status_code)
        self.assertNotIn('data', response.get_json())

    def test_currency_precision_and_zero_stock_threshold_preserved(self):
        from pos_system.models.pos_config import PosConfig
        from pos_system.models.res_currency import ResCurrency
        config = PosConfig.search([])[0]
        currency = ResCurrency.create({'name': 'Test', 'symbol': 'TEST', 'iso_code': 'TST',
                                       'decimal_places': 3, 'position': 'after'})
        config.write({'currency_id': currency.id, 'low_stock_threshold': 0})
        data = self.query(self.client()).get_json()['data']
        self.assertEqual(3, data['currency']['decimal_places'])
        self.assertEqual('after', data['currency']['position'])
        self.assertEqual(701.5, data['summary']['revenue'])
        self.assertEqual(0, data['stock']['threshold'])
        self.assertEqual(0, data['stock']['low'])


class DashboardIntegrationTests(unittest.TestCase):
    def test_dashboard_translation_dictionaries_are_complete(self):
        folder = Path(__file__).resolve().parents[1] / 'pos_system' / 'i18n'
        dictionaries = {}
        for language in ('en', 'fr'):
            with (folder / (language + '.json')).open(encoding='utf-8') as source:
                dictionaries[language] = {key: value for key, value in json.load(source).items()
                                          if key.startswith('bi.')}
        self.assertEqual(set(dictionaries['en']), set(dictionaries['fr']))
        self.assertGreater(len(dictionaries['en']), 60)
        for key in dictionaries['en']:
            for language in dictionaries:
                self.assertTrue(dictionaries[language][key].strip(), (language, key))
        self.assertEqual('Dashboard', dictionaries['en']['bi.title'])
        self.assertEqual('Tableau de bord', dictionaries['fr']['bi.title'])
        self.assertNotEqual(dictionaries['en']['bi.error'], dictionaries['fr']['bi.error'])

    def test_isolated_dashboard_scenarios(self):
        with tempfile.TemporaryDirectory() as temp:
            environment = dict(os.environ, DATABASE_URL='', DB_PATH=os.path.join(temp, 'dashboard.db'),
                               POS_OFFLINE_MODE='', OFFLINE_SYNC_ENABLED='')
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--isolated'],
                                    cwd=Path(__file__).resolve().parents[1], env=environment,
                                    capture_output=True, text=True, timeout=90)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)


if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if '--isolated' in sys.argv:
        scenarios = type('DashboardReportingTests', (DashboardScenarios, unittest.TestCase), {})
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(scenarios))
        sys.exit(not result.wasSuccessful())
    unittest.main()
