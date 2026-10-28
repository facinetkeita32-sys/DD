import json
import urllib.request
import urllib.error
import threading
from collections import OrderedDict
from datetime import date, datetime

from .. import db
from ..odoo_orm import Model, Many2many, Boolean, _db_cache, _db_lock

_last_backup_time = None
_auto_backup_thread = None
_auto_backup_running = False
_auto_backup_stop = None
_backup_settings = {}

LEGACY_TABLES = {
    'currencies': 'res.currency', 'companies': 'res.company',
    'configs': 'pos.config', 'product_categories': 'product.category',
    'pos_categories': 'pos.category', 'payment_methods': 'pos.payment.method',
    'taxes': 'pos.tax', 'delivery_zones': 'delivery.zone',
    'users': 'res.users', 'customers': 'res.partner',
    'products': 'product.product', 'orders': 'pos.order',
    'order_lines': 'pos.order.line', 'sessions': 'pos.session',
    'payments': 'pos.payment', 'languages': 'res.lang', 'logs': 'login.log',
}


def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def _registry():
    # Import every model so backups include all application tables, not a fixed subset.
    from .. import models  # noqa: F401
    models_by_table = {model._name: model for model in Model.__subclasses__()}
    relations = {}
    for table, model in models_by_table.items():
        for field in model._fields.values():
            if isinstance(field, Many2many):
                rel = field.rel or f'{table}_{field.comodel_name}_rel'
                relations[rel] = (
                    field.column1 or f'{table}_id',
                    field.column2 or f'{field.comodel_name}_id',
                )
    return models_by_table, relations


def _read_rows(conn, table):
    cur = conn.cursor()
    try:
        cur.execute('SELECT * FROM ' + _quote(table))
        columns = [description[0] for description in cur.description]
        return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        cur.close()


def _json_value(value):
    return value.isoformat() if isinstance(value, (datetime, date)) else value


def _begin(conn, snapshot=False):
    if db._use_pg:
        conn.autocommit = False
        if snapshot:
            cur = conn.cursor()
            cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            cur.close()
    else:
        conn.execute('BEGIN' if snapshot else 'BEGIN IMMEDIATE')


def export_full_backup(env=None):
    models, relations = _registry()
    with _db_lock:
        conn = db.get_conn()
        try:
            _begin(conn, snapshot=True)
            tables = {
                table: [{key: _json_value(value) for key, value in row.items()}
                        for row in _read_rows(conn, table)]
                for table in sorted(set(models) | set(relations))
            }
            sequences = {
                table: max(_db_cache.get(table, {}).get('_seq', 0),
                           max((row['id'] for row in tables[table]), default=0))
                for table in models
            }
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    return {
        'format': 'shop-with-dd-pos', 'version': '3.0',
        'exported_at': datetime.now().isoformat(),
        'tables': tables, 'sequences': sequences,
    }


def push_backup(url, api_key=None, env=None):
    global _last_backup_time
    try:
        payload = json.dumps(export_full_backup(env)).encode('utf-8')
        req = urllib.request.Request(url, data=payload, method='POST')
        req.add_header('Content-Type', 'application/json')
        if api_key:
            req.add_header('Authorization', f'Bearer {api_key}')
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode('utf-8')
        _last_backup_time = datetime.now().isoformat()
        return {'success': True, 'message': 'Backup pushed successfully', 'response': body}
    except urllib.error.HTTPError as e:
        return {'success': False, 'message': f'HTTP {e.code}: {e.read().decode("utf-8", errors="replace")}'}
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


def _validate_backup(data, conn, models, relations):
    if not isinstance(data, dict):
        raise ValueError('Backup must be a JSON object')
    # Also accept the JSON wrapper returned by the old /export endpoint.
    if data.get('success') is True and isinstance(data.get('data'), dict):
        data = data['data']
    warnings = []
    sequences = {}
    if data.get('version') == '3.0':
        if data.get('format') != 'shop-with-dd-pos' or not isinstance(data.get('tables'), dict):
            raise ValueError('Invalid full backup format')
        tables = data['tables']
        expected = set(models) | set(relations)
        if set(tables) != expected:
            raise ValueError('Backup tables do not match this application version; no data was changed')
        sequences = data.get('sequences', {})
        if not isinstance(sequences, dict) or set(sequences) - set(models):
            raise ValueError('Invalid backup sequences')
    elif data.get('version') in (None, '1.0', '2.0'):
        tables = {table: data[key] for key, table in LEGACY_TABLES.items() if key in data}
        if not tables:
            raise ValueError('No recognized backup records found')
        warnings.append('Legacy backup: records omitted by the old exporter cannot be recovered '
                        '(including product tax/category links, logs, languages and backup settings). '
                        'Tables absent from this file were kept.')
    else:
        raise ValueError('Unsupported backup version')

    normalized = {}
    for table, rows in tables.items():
        if not isinstance(rows, list):
            raise ValueError(f'{table}: expected a list of records')
        columns = db.get_table_columns(conn, table)
        seen = set()
        normalized[table] = []
        for row in rows:
            if not isinstance(row, dict) or not row or set(row) - columns:
                raise ValueError(f'{table}: invalid record or unknown columns')
            if data.get('version') == '3.0' and set(row) != columns:
                raise ValueError(f'{table}: incomplete record')
            if table in models:
                rid = row.get('id')
                if type(rid) is not int or rid <= 0 or rid in seen:
                    raise ValueError(f'{table}: missing, invalid or duplicate record ID')
                seen.add(rid)
            elif set(row) != set(relations[table]):
                raise ValueError(f'{table}: invalid relationship columns')
            converted = {}
            for key, value in row.items():
                if not isinstance(value, (str, int, float, bool, type(None))):
                    raise ValueError(f'{table}.{key}: invalid value')
                field = models[table]._fields.get(key) if table in models else None
                if isinstance(field, Boolean):
                    if value not in (True, False, 0, 1, None):
                        raise ValueError(f'{table}.{key}: invalid boolean')
                    value = bool(value) if value is not None else None
                elif isinstance(value, bool):
                    # Legacy exports encode empty many-to-one IDs as false.
                    value = int(value)
                converted[key] = value
            normalized[table].append(converted)
    for table, seq in sequences.items():
        if type(seq) is not int or seq < 0:
            raise ValueError(f'{table}: invalid sequence')
    for row in normalized.get('backup.settings', []):
        if (row['id'] != 1 or type(row.get('interval_minutes')) is not int
                or row['interval_minutes'] < 1
                or not isinstance(row.get('url'), str)
                or not isinstance(row.get('api_key'), str)):
            raise ValueError('Invalid saved backup settings')
    return normalized, sequences, warnings


def _build_cache(conn, models, sequences):
    cache = {}
    for table in models:
        rows = _read_rows(conn, table)
        records = OrderedDict((row['id'], row) for row in sorted(rows, key=lambda row: row['id']))
        cache[table] = {'_seq': max(max(records, default=0), sequences.get(table, 0)),
                        '_data': records}
    return cache


def restore_from_data(env, data):
    models, relations = _registry()
    with _db_lock:
        conn = db.get_conn()
        try:
            _begin(conn)
            tables, sequences, warnings = _validate_backup(data, conn, models, relations)
            cur = conn.cursor()
            try:
                # Clear relationship tables first. For old files, only clear links
                # involving replaced tables, rather than retaining unrelated stale IDs.
                for rel in relations:
                    if rel in tables or any(col.removesuffix('_id') in tables for col in relations[rel]):
                        cur.execute('DELETE FROM ' + _quote(rel))
                for table in tables:
                    if table in models:
                        cur.execute('DELETE FROM ' + _quote(table))
                for table, rows in tables.items():
                    for row in rows:
                        cols = list(row)
                        sql = 'INSERT INTO {} ({}) VALUES ({})'.format(
                            _quote(table), ','.join(_quote(col) for col in cols),
                            ','.join([db.param_style()] * len(cols)))
                        cur.execute(sql, [row[col] for col in cols])
                cache = _build_cache(conn, models, sequences)
                if db._use_pg:
                    for table in models:
                        cur.execute('SELECT pg_get_serial_sequence(%s, %s)', (_quote(table), 'id'))
                        sequence = cur.fetchone()[0]
                        if sequence:
                            # Sequence name comes from PostgreSQL, never from the file.
                            cur.execute(f'ALTER SEQUENCE {sequence} RESTART WITH {cache[table]["_seq"] + 1}')
            finally:
                cur.close()
            conn.commit()
        except Exception as e:
            conn.rollback()
            return {'success': False, 'error': f'Restore failed; no data was changed: {e}'}
        finally:
            conn.close()
        # Publish only after every table was committed successfully. Keep the dict
        # identity because routes and startup code hold references to it.
        _db_cache.clear()
        _db_cache.update(cache)
        if 'backup.settings' in tables:
            load_backup_settings(env)
        count = sum(len(rows) for rows in tables.values())
        return {'success': True, 'message': f'Restored {count} records',
                'warnings': warnings, 'details': {'counts': {table: len(rows) for table, rows in tables.items()}}}


def get_backup_status():
    return {
        'last_backup': _last_backup_time,
        'auto_backup_running': _auto_backup_running,
        'settings': {
            'url': _backup_settings.get('url', ''),
            'interval_minutes': _backup_settings.get('interval_minutes', 60),
            'has_api_key': bool(_backup_settings.get('api_key')),
        }
    }


def load_backup_settings(env=None):
    global _backup_settings
    rows = _db_cache.get('backup.settings', {}).get('_data', {})
    _backup_settings = dict(rows.get(1, {}))
    if _backup_settings.get('auto_backup') and _backup_settings.get('url'):
        start_auto_backup(_backup_settings.get('interval_minutes') or 60,
                          _backup_settings['url'], _backup_settings.get('api_key'), env)
    else:
        stop_auto_backup()


def save_backup_settings(settings, env=None):
    try:
        interval = int(settings.get('interval_minutes', 60))
        if interval < 1:
            raise ValueError('Backup interval must be at least one minute')
        values = {
            'url': settings.get('url', '').strip(),
            'api_key': settings.get('api_key', '').strip(),
            'interval_minutes': interval,
            'auto_backup': bool(settings.get('auto_backup', False)),
        }
        with _db_lock:
            conn = db.get_conn()
            try:
                _begin(conn)
                db.insert_or_update(conn, 'backup.settings', values, 1)
                rows = _read_rows(conn, 'backup.settings')
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            _db_cache['backup.settings'] = {
                '_seq': max(row['id'] for row in rows),
                '_data': OrderedDict((row['id'], row) for row in rows),
            }
            load_backup_settings(env)
        return {'success': True, 'message': 'Backup settings saved'}
    except (ValueError, TypeError) as e:
        return {'success': False, 'error': str(e)}


def start_auto_backup(interval_minutes, url, api_key=None, env=None):
    global _auto_backup_thread, _auto_backup_running, _auto_backup_stop
    stop_auto_backup()
    stop_event = threading.Event()
    _auto_backup_stop = stop_event
    _auto_backup_running = True

    def _run():
        # Waiting is interruptible, so replacing settings cannot leave an old
        # sleeping worker pushing backups alongside the new worker.
        while not stop_event.wait(interval_minutes * 60):
            push_backup(url, api_key, env)

    _auto_backup_thread = threading.Thread(target=_run, daemon=True)
    _auto_backup_thread.start()


def stop_auto_backup():
    global _auto_backup_running, _auto_backup_thread
    if _auto_backup_stop is not None:
        _auto_backup_stop.set()
    _auto_backup_running = False
    _auto_backup_thread = None
