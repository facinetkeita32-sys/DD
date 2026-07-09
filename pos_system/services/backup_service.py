import json
import urllib.request
import urllib.error
import os
import threading
import time
from datetime import datetime

_last_backup_time = None
_auto_backup_thread = None
_auto_backup_running = False
_backup_settings = {}

def export_full_backup(env):
    from ..models.product_product import ProductProduct
    from ..models.product_category import ProductCategory
    from ..models.pos_category import PosCategory
    from ..models.pos_order import PosOrder
    from ..models.pos_order_line import PosOrderLine
    from ..models.res_partner import ResPartner
    from ..models.pos_payment_method import PosPaymentMethod
    from ..models.pos_tax import PosTax
    from ..models.delivery_zone import DeliveryZone
    from ..models.res_users import ResUsers
    from ..models.pos_config import PosConfig
    from ..models.res_company import ResCompany
    from ..models.res_currency import ResCurrency
    from ..models.pos_session import PosSession
    from ..models.pos_payment import PosPayment

    def _serialize(records):
        return [dict(r._data) for r in records]

    products = ProductProduct.search([])
    categories = ProductCategory.search([])
    pos_cats = PosCategory.search([])
    orders = PosOrder.search([])
    order_lines = PosOrderLine.search([])
    customers = ResPartner.search([])
    payment_methods = PosPaymentMethod.search([])
    taxes = PosTax.search([])
    delivery_zones = DeliveryZone.search([])
    users = ResUsers.search([])
    configs = PosConfig.search([])
    companies = ResCompany.search([])
    currencies = ResCurrency.search([])
    sessions = PosSession.search([])
    payments = PosPayment.search([])

    data = {
        'exported_at': datetime.now().isoformat(),
        'version': '2.0',
        'products': _serialize(products),
        'product_categories': _serialize(categories),
        'pos_categories': _serialize(pos_cats),
        'orders': _serialize(orders),
        'order_lines': _serialize(order_lines),
        'customers': _serialize(customers),
        'payment_methods': _serialize(payment_methods),
        'taxes': _serialize(taxes),
        'delivery_zones': _serialize(delivery_zones),
        'users': _serialize(users),
        'configs': _serialize(configs),
        'companies': _serialize(companies),
        'currencies': _serialize(currencies),
        'sessions': _serialize(sessions),
        'payments': _serialize(payments),
    }
    return data


def push_backup(url, api_key=None, env=None):
    global _last_backup_time
    data = export_full_backup(env)
    payload = json.dumps(data).encode('utf-8')
    req = urllib.request.Request(url, data=payload, method='POST')
    req.add_header('Content-Type', 'application/json')
    if api_key:
        req.add_header('Authorization', f'Bearer {api_key}')
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        body = resp.read().decode('utf-8')
        _last_backup_time = datetime.now().isoformat()
        return {'success': True, 'message': 'Backup pushed successfully', 'response': body}
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='replace')
        return {'success': False, 'message': f'HTTP {e.code}: {body}'}
    except Exception as e:
        return {'success': False, 'message': str(e)}


def save_backup_to_file(env, filepath):
    data = export_full_backup(env)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {'success': True, 'message': f'Backup saved to {filepath}'}


def restore_from_backup_file(env, filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return restore_from_data(env, data)


def restore_from_data(env, data):
    from ..odoo_orm import _db_cache

    results = {'restored': [], 'errors': []}

    tables = [
        ('currencies', 'res.currency'),
        ('companies', 'res.company'),
        ('configs', 'pos.config'),
        ('product_categories', 'product.category'),
        ('pos_categories', 'pos.category'),
        ('payment_methods', 'pos.payment.method'),
        ('taxes', 'pos.tax'),
        ('delivery_zones', 'delivery.zone'),
        ('users', 'res.users'),
        ('customers', 'res.partner'),
        ('products', 'product.product'),
        ('orders', 'pos.order'),
        ('order_lines', 'pos.order.line'),
        ('sessions', 'pos.session'),
        ('payments', 'pos.payment'),
    ]

    for key, model_name in tables:
        if key not in data:
            continue
        for record_data in data[key]:
            tname = model_name.replace('.', '_')
            if tname not in _db_cache:
                _db_cache[tname] = {'_data': [], '_seq': 0}
            existing = [r for r in _db_cache[tname]['_data'] if r.get('id') == record_data.get('id')]
            if existing:
                existing[0].update(record_data)
                results['restored'].append(f"Updated {model_name} id={record_data.get('id')}")
            else:
                _db_cache[tname]['_data'].append(dict(record_data))
                results['restored'].append(f"Added {model_name} id={record_data.get('id')}")

    return {'success': True, 'message': f"Restored {len(results['restored'])} records", 'details': results}


def get_backup_status():
    global _backup_settings, _last_backup_time, _auto_backup_running
    return {
        'last_backup': _last_backup_time,
        'auto_backup_running': _auto_backup_running,
        'settings': {
            'url': _backup_settings.get('url', ''),
            'interval_minutes': _backup_settings.get('interval_minutes', 60),
            'has_api_key': bool(_backup_settings.get('api_key')),
        }
    }


def save_backup_settings(settings, env=None):
    global _backup_settings
    _backup_settings['url'] = settings.get('url', '').strip()
    _backup_settings['api_key'] = settings.get('api_key', '').strip()
    _backup_settings['interval_minutes'] = int(settings.get('interval_minutes', 60))
    auto_backup = settings.get('auto_backup', False)
    if auto_backup and _backup_settings['url']:
        start_auto_backup(_backup_settings['interval_minutes'], _backup_settings['url'], _backup_settings['api_key'], env)
    else:
        stop_auto_backup()
    return {'success': True, 'message': 'Backup settings saved'}


def start_auto_backup(interval_minutes, url, api_key=None, env=None):
    global _auto_backup_thread, _auto_backup_running
    stop_auto_backup()
    _auto_backup_running = True
    def _run():
        while _auto_backup_running:
            push_backup(url, api_key, env)
            time.sleep(interval_minutes * 60)
    _auto_backup_thread = threading.Thread(target=_run, daemon=True)
    _auto_backup_thread.start()


def stop_auto_backup():
    global _auto_backup_running, _auto_backup_thread
    _auto_backup_running = False
    _auto_backup_thread = None
