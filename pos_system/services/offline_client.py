"""Local-only provisioning, password verification and durable outbox transport."""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from werkzeug.security import check_password_hash, generate_password_hash

from .. import db
from ..odoo_orm import _db_cache, _db_lock
from ..models.res_users import ResUsers
from ..models.pos_order import PosOrder
from ..models.pos_order_line import PosOrderLine
from ..models.pos_payment import PosPayment
from ..models.pos_session import PosSession
from . import offline_store as store
from .offline_server import SyncError, REFERENCE_MODELS
from .backup_service import _registry, _build_cache, _quote
from .unit_of_work import atomic

_sync_lock = threading.Lock()
_worker = None
_stop = threading.Event()


class NetworkUnavailable(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def server_url(value):
    if not isinstance(value, str):
        raise SyncError('Enter the HTTPS server address.')
    parsed = urllib.parse.urlsplit(value.strip().rstrip('/'))
    loopback = parsed.hostname in ('127.0.0.1', 'localhost') and os.environ.get('OFFLINE_ALLOW_HTTP') == '1'
    if (parsed.scheme != 'https' and not (parsed.scheme == 'http' and loopback)
            or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
        raise SyncError('Use an HTTPS server origin without credentials or a path.')
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, '', '', ''))


def request_server(config, path, body=None, credential=None):
    headers = {'Content-Type': 'application/json'}
    if credential or config.get('credential'):
        headers['Authorization'] = 'Bearer ' + (credential or config['credential'])
    if config.get('server_id'):
        headers['X-POS-Server'] = config['server_id']
        headers['X-POS-Epoch'] = config['epoch']
    if path == 'catalogue':
        grant = config.get('_catalog_grant')
        if not grant:
            with _db_lock:
                grants = [row for _, row in store.all_rows('grants')
                          if row.get('user', {}).get('role') in ('admin', 'manager')
                          and row.get('expires_at', 0) > effective_time(config)]
            grant = max(grants, key=lambda row: row['issued_at']) if grants else None
        if grant:
            headers['X-POS-User-Grant'] = grant['id']
            headers['X-POS-User-Token'] = grant['token']
    request = urllib.request.Request(config['server_url'] + '/api/offline/' + path,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=8) as response:
            result = json.load(response)
            if not result.get('success'):
                raise SyncError('Invalid synchronization response.', 502)
            return result['data']
    except urllib.error.HTTPError as e:
        try:
            error = json.load(e)
        except (ValueError, OSError):
            error = {}
        raise SyncError(error.get('error') or 'Server rejected synchronization.', e.code,
                        error.get('code') or 'server', details=error.get('details')) from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NetworkUnavailable('Server unavailable; local sales remain saved.') from e


def config():
    return store.get('meta', 'client')


def effective_time(settings=None):
    settings = settings or config() or {}
    return time.time() + settings.get('clock_offset', 0)


def check_access(user_id):
    if type(user_id) is not int:
        raise SyncError('Unauthorized', 401, 'grant')
    settings = config()
    grant = store.get('grants', str(user_id))
    users = ResUsers.browse(user_id)
    from ..permissions import role_has_permission
    if (not settings or settings.get('blocked') or not grant or not users or not users[0].active
            or not role_has_permission(users[0].role, 'order.create')
            or effective_time(settings) > grant['expires_at']
            or effective_time(settings) < settings.get('last_server_time', 0) - 300):
        raise SyncError('Online sign-in is required to renew this terminal authorization.', 401, 'grant')


def _reload():
    models, _ = _registry()
    sequences = {name: data.get('_seq', 0) for name, data in _db_cache.items()}
    cache = _build_cache(db.get_conn(), models, sequences)
    _db_cache.clear()
    _db_cache.update(cache)


def _cache_grant(grant, password):
    user = grant['user']
    values = {key: user.get(key) for key in ('login', 'name', 'role', 'lang', 'active')}
    values['password'] = generate_password_hash(password)
    db.insert_or_update(db.get_conn(), 'res.users', values, user['id'])
    store.put('grants', str(user['id']), grant)


def apply_catalogue(snapshot):
    models, relations = _registry()
    allowed = set(REFERENCE_MODELS) | {name for name in relations
                                      if any(name.startswith(model + '_') for model in REFERENCE_MODELS)}
    if set(snapshot.get('tables', {})) != allowed:
        raise SyncError('Catalogue schema differs from this desktop version.', 409, 'version')
    from .offline_catalog import remap_snapshot
    snapshot = remap_snapshot(snapshot)
    conn = db.get_conn()
    cur = conn.cursor()
    try:
        for name in sorted(allowed):
            rows = snapshot['tables'][name]
            if not isinstance(rows, list):
                raise SyncError('Invalid catalogue.')
            columns = db.get_table_columns(conn, name)
            cur.execute('DELETE FROM ' + _quote(name))
            for row in rows:
                if not isinstance(row, dict) or not row or set(row) - columns:
                    raise SyncError('Invalid catalogue columns.')
                cols = list(row)
                cur.execute('INSERT INTO {} ({}) VALUES ({})'.format(
                    _quote(name), ','.join(_quote(col) for col in cols),
                    ','.join([db.param_style()] * len(cols))), [row[col] for col in cols])
        # Keep only locally verified credentials. Server profiles never contain
        # passwords, and revocations are applied at the next successful pull.
        cur.execute('UPDATE "res.users" SET active=0')
        for user in snapshot.get('users', []):
            existing = ResUsers.browse(user['id'])
            if existing:
                values = {key: user[key] for key in ('login', 'name', 'role', 'lang', 'active') if key in user}
                db.insert_or_update(conn, 'res.users', values, user['id'])
    finally:
        cur.close()


def enroll(body):
    if config():
        raise SyncError('This terminal is already paired. Keep its database and pending sales.', 409)
    if any(table['_data'] for table in _db_cache.values()):
        raise SyncError('Provisioning requires a fresh terminal database; existing records were kept.', 409)
    url = server_url(body.get('server_url'))
    provisional = {'server_url': url}
    registration = request_server(provisional, 'register', {
        'login': body.get('login'), 'password': body.get('password'),
        'device_name': body.get('device_name'),
    })
    settings = dict(provisional, **{key: registration[key] for key in
                                   ('device_id', 'credential', 'server_id', 'epoch')})
    snapshot = request_server(dict(settings, _catalog_grant=registration['grant']), 'catalogue')
    with atomic():
        apply_catalogue(snapshot)
        _cache_grant(registration['grant'], body['password'])
        settings.update(clock_offset=snapshot['server_time'] - time.time(),
                        last_server_time=snapshot['server_time'], last_sync=time.time(),
                        device_name=body['device_name'], connected=True, blocked=False)
        store.put('meta', 'client', settings)
        _reload()
    return {'ready': True, 'login': registration['grant']['user']['login']}


def authenticate(login, password):
    settings = config()
    if not settings:
        raise SyncError('Register this terminal online first.', 409, 'setup')
    try:
        grant = request_server(settings, 'authorize', {'login': login, 'password': password})
        with atomic():
            _cache_grant(grant, password)
            settings.update(blocked=False, connected=True,
                            clock_offset=grant['issued_at'] - time.time(), last_server_time=grant['issued_at'])
            store.put('meta', 'client', settings)
            _reload()
        return ResUsers.browse(grant['user_id'])
    except NetworkUnavailable:
        users = ResUsers.search([('login', '=', login), ('active', '=', True)], limit=1)
        if not users or not check_password_hash(users[0]._data.get('password') or '', password):
            raise SyncError('Invalid credentials.', 401, 'credentials')
        check_access(users[0].id)
        return users
    except SyncError as error:
        if error.code in ('revoked', 'epoch', 'scope', 'device', 'grant'):
            settings['blocked'] = True
            settings['error'] = error.code
            store.put('meta', 'client', settings)
        raise


def _uuid(model, record_id):
    key = f'local:{model}:{record_id}'
    value = store.get('meta', key)
    if value is None:
        value = str(uuid.uuid4())
        store.put('meta', key, value)
    return value


def capture(kind, record_id, user_id):
    check_access(user_id)
    if kind == 'sale':
        record = PosOrder.browse(record_id)[0]
        if record.state != 'paid':
            raise SyncError('Offline mode supports fully paid cash sales only.')
        payload = dict(record._data)
        payload['uuid'] = _uuid('pos.order', record_id)
        settings = config()
        reference = 'OFF-' + settings['device_id'][:8] + '-' + payload['uuid']
        record.write({'name': reference, 'pos_reference': reference})
        payload.update(name=reference, pos_reference=reference)
        payload['session_uuid'] = (_uuid('pos.session', record._data['session_id'])
                                   if record._data.get('session_id') else None)
        payload['lines'] = [dict(line._data, tax_ids=line.read(['tax_ids'])['tax_ids'])
                            for line in PosOrderLine.search([('order_id', '=', record_id)])]
        payload['payments'] = [dict(p._data) for p in PosPayment.search([('order_id', '=', record_id)])]
        from .offline_catalog import reference
        for line in payload['lines']:
            line['product_ref'] = reference('product.product', line['product_id'])
            line['tax_refs'] = [reference('pos.tax', tid) for tid in line['tax_ids']]
        for payment in payload['payments']:
            payment['method_ref'] = reference('pos.payment.method', payment['payment_method_id'])
        payload['customer_ref'] = reference('res.partner', payload.get('partner_id'))
        payload['delivery_ref'] = reference('delivery.zone', payload.get('delivery_zone_id'))
        from ..models.pos_payment_method import PosPaymentMethod
        for payment in payload['payments']:
            methods = PosPaymentMethod.browse(payment['payment_method_id'])
            if not methods or not methods[0].is_cash:
                raise SyncError('Offline mode supports cash payments only.')
    else:
        record = PosSession.browse(record_id)[0]
        if record._data.get('user_id') != user_id:
            raise SyncError('This session belongs to another cashier.', 403)
        payload = dict(record._data, uuid=_uuid('pos.session', record_id))
        record.write({'name': 'OFF-' + config()['device_id'][:8] + '-' + payload['uuid']})
    enqueue(kind, payload, record_id, user_id)
    return record


def enqueue(kind, payload, record_id, user_id, sequence=None):
    grant = store.get('grants', str(user_id))
    if sequence is None:
        sequence = store.get('meta', 'outbox_sequence', 0) + 1
        store.put('meta', 'outbox_sequence', sequence)
    key = str(uuid.uuid4())
    operation = {'id': key, 'kind': kind, 'data': payload, 'created_at': effective_time(),
                 'grant': {'id': grant['id'], 'token': grant['token']}}
    store.put('outbox', key, {'sequence': sequence, 'user_id': user_id, 'operation': operation,
                              'status': 'pending', 'local_id': record_id})
    return key


def capture_change(model, before, record_ids, creating, user_id):
    from .offline_catalog import project, encode
    from ..odoo_orm import env
    for record_id in record_ids:
        records = env[model].browse(record_id)
        if not records:
            raise SyncError('The changed record could not be queued.')
        after = project(model, records[0])
        key = _uuid(model, record_id)
        if creating:
            store.put('meta', f'catalog-new:{model}:{record_id}', key)
            if model == 'product.product':
                store.put('meta', f'catalog-cost-known:{record_id}', True)
            values, base = after, {}
        else:
            values = {name: value for name, value in after.items() if value != before[record_id][name]}
            base = {name: before[record_id][name] for name in values}
        if not values:
            continue
        from .offline_catalog import reference
        payload = {'uuid': key, 'model': model, 'action': 'create' if creating else 'update',
                   'record': reference(model, record_id), 'values': encode(model, values),
                   'base': encode(model, base)}
        if not creating and model == 'product.product' and 'available_qty' in values:
            payload['stock_delta'] = values['available_qty'] - base['available_qty']
        enqueue('catalog', payload, record_id, user_id)


def pending():
    return sorted([(key, row) for key, row in store.all_rows('outbox') if row['status'] not in ('sent', 'superseded')],
                  key=lambda item: item[1]['sequence'])


def synchronize():
    if not _sync_lock.acquire(blocking=False):
        return
    try:
        with _db_lock:
            settings = config()
        if not settings or settings.get('blocked'):
            return
        try:
            while True:
                with _db_lock:
                    queue = pending()
                if not queue:
                    break
                key, row = queue[0]
                if row['status'] == 'conflict':
                    return
                receipt = request_server(settings, 'push', {'operation': row['operation']})
                if receipt.get('id') != key or receipt.get('kind') != row['operation']['kind']:
                    raise SyncError('Server acknowledgement does not match the operation.', 409, 'protocol')
                with atomic():
                    resource = receipt.get('resource')
                    if resource:
                        from .offline_catalog import map_id
                        if (resource.get('model') != row['operation']['data'].get('model')
                                or resource.get('uuid') != row['operation']['data'].get('uuid')):
                            raise SyncError('Catalogue acknowledgement mismatch.', 409, 'protocol')
                        map_id(resource['model'], row['local_id'], resource['server_id'])
                    row.update(status='sent', receipt=receipt)
                    store.put('outbox', key, row)
            snapshot = request_server(settings, 'catalogue')
            with atomic():
                if not pending():
                    apply_catalogue(snapshot)
                    _reload()
                settings.update(last_sync=time.time(), connected=True, error=None,
                                clock_offset=snapshot['server_time'] - time.time(),
                                last_server_time=snapshot['server_time'])
                store.put('meta', 'client', settings)
        except (SyncError, NetworkUnavailable) as error:
            with atomic():
                if isinstance(error, SyncError) and error.code == 'catalog_conflict' and queue:
                    conflict_key, conflict_row = queue[0]
                    conflict_row.update(status='conflict', conflict=error.details or {}, message=str(error))
                    store.put('outbox', conflict_key, conflict_row)
                settings['connected'] = not isinstance(error, NetworkUnavailable)
                settings['error'] = getattr(error, 'code', 'network')
                settings['blocked'] = getattr(error, 'code', '') in ('revoked', 'epoch', 'scope', 'device', 'grant')
                store.put('meta', 'client', settings)
    finally:
        _sync_lock.release()


def start_worker():
    global _worker
    if _worker and _worker.is_alive():
        return
    _stop.clear()

    def run():
        while not _stop.wait(15):
            try:
                synchronize()
            except Exception:
                # A worker failure never removes the durable queue. Try again
                # next interval; diagnostic details remain off public responses.
                pass
    _worker = threading.Thread(target=run, daemon=True, name='offline-sync')
    _worker.start()


def stop_worker():
    _stop.set()
