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
    try:
        from ..odoo_orm import _db_cache, _write_cache_version, DB_ONLY_TABLES, get_conn, put_conn, HEAVY_COLS, _persist_write
    except ImportError:
        from ..odoo_orm import _db_cache, get_conn, put_conn
        DB_ONLY_TABLES = set()
        HEAVY_COLS = set()
        _write_cache_version = lambda: None
        _persist_write = None
    from collections import OrderedDict

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
            try:
                if model_name in DB_ONLY_TABLES:
                    # DB_ONLY: upsert directly to PostgreSQL
                    conn = get_conn()
                    try:
                        # Build upsert
                        cols = [k for k in record_data.keys() if k != 'id']
                        # Ensure id is present
                        if 'id' not in record_data:
                            continue
                        rid = record_data['id']
                        # Check existing
                        cur = conn.cursor()
                        cur.execute('SELECT 1 FROM "{}" WHERE id=%s'.format(model_name), (rid,))
                        exists = cur.fetchone()
                        if exists:
                            # Update
                            set_clause = ', '.join(['"{}"=%s'.format(c) for c in cols])
                            vals = [record_data[c] for c in cols] + [rid]
                            cur.execute('UPDATE "{}" SET {} WHERE id=%s'.format(model_name, set_clause), vals)
                        else:
                            all_cols = ['id'] + cols
                            placeholders = ', '.join(['%s'] * len(all_cols))
                            qcols = ', '.join(['"{}"'.format(c) for c in all_cols])
                            vals = [rid] + [record_data[c] for c in cols]
                            cur.execute('INSERT INTO "{}" ({}) VALUES ({})'.format(model_name, qcols, placeholders), vals)
                        conn.commit()
                        cur.close()
                    finally:
                        put_conn(conn)
                    results['restored'].append(f"Added {model_name} id={record_data.get('id')}")
                else:
                    # Cached: update _db_cache with dot key and persist
                    if model_name not in _db_cache:
                        _db_cache[model_name] = {'_seq': 0, '_data': OrderedDict()}
                    tbl = _db_cache[model_name]
                    rid = record_data.get('id')
                    if rid is None:
                        continue
                    # Update seq
                    if rid > tbl['_seq']:
                        tbl['_seq'] = rid
                    # Convert _data if it's list (legacy)
                    if isinstance(tbl['_data'], list):
                        od = OrderedDict()
                        for r in tbl['_data']:
                            od[r.get('id')] = r
                        tbl['_data'] = od
                    # Update or add
                    if rid in tbl['_data']:
                        tbl['_data'][rid].update(record_data)
                        results['restored'].append(f"Updated {model_name} id={rid}")
                    else:
                        tbl['_data'][rid] = dict(record_data)
                        results['restored'].append(f"Added {model_name} id={rid}")
                    # Persist to DB for cached tables (light cols)
                    try:
                        if _persist_write is None:
                            raise ImportError("no persist")
                        # Use direct SQL for simplicity
                        conn = get_conn()
                        try:
                            # Build light cols (exclude heavy)
                            cols = [k for k in record_data.keys() if k not in HEAVY_COLS and k != 'id']
                            if cols:
                                qcols = ['"{}"'.format(c) for c in cols]
                                all_cols = '"id",' + ','.join(qcols)
                                all_ph = '%s,' + ','.join(['%s' for _ in cols])
                                update_set = ', '.join(['{}=EXCLUDED.{}'.format(q, q) for q in qcols])
                                sql = 'INSERT INTO "{}" ({}) VALUES ({}) ON CONFLICT (id) DO UPDATE SET {}'.format(model_name, all_cols, all_ph, update_set)
                                vals = [rid] + [record_data[c] for c in cols]
                                cur = conn.cursor()
                                cur.execute(sql, vals)
                                conn.commit()
                                cur.close()
                        finally:
                            put_conn(conn)
                    except Exception:
                        pass
            except Exception as e:
                results['errors'].append(f"{model_name} id={record_data.get('id')}: {str(e)}")
    try:
        _write_cache_version()
    except Exception:
        pass
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
