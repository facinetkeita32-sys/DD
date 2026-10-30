"""Local request boundary: cash checkout + outbox commit, or neither."""
import json
from flask import request, jsonify, session, g

from . import offline_store as store
from .offline_server import SyncError
from .unit_of_work import atomic


class Rollback(Exception):
    pass


def before_request():
    if not store.local_mode() or not request.path.startswith('/api/'):
        return None
    host = request.host.partition(':')[0]
    origin = request.headers.get('Origin')
    if host not in ('localhost', '127.0.0.1') or (origin and origin != request.host_url.rstrip('/')):
        return jsonify(error='Local terminal origin required.'), 403
    public = (request.path in ('/api/auth/login', '/api/offline/status', '/api/offline/enroll')
              or request.path.startswith('/api/translations/'))
    if public:
        return None
    from .offline_client import check_access
    try:
        from ..session_security import session_generation
        if session.get('generation') != session_generation():
            raise SyncError('Unauthorized', 401, 'grant')
        check_access(session.get('user_id'))
    except SyncError as e:
        session.clear()
        return jsonify(error=str(e), code=e.code), e.status
    from ..models.res_users import ResUsers
    from ..permissions import role_has_permission
    g.user_role = ResUsers.browse(session['user_id'])[0].role
    if request.path.startswith(('/api/backup/', '/api/system/', '/api/offline/register',
                                '/api/offline/authorize', '/api/offline/push', '/api/offline/catalogue')):
        return jsonify(error='This operation is unavailable on an offline terminal.'), 403
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        from .offline_catalog import ROUTES
        allowed = (request.endpoint in ('api.create_order', 'api.create_session', 'api.open_session', 'api.close_session')
                   or request.endpoint in ROUTES
                   or request.path in ('/api/auth/logout', '/api/settings/language', '/api/offline/sync')
                   or request.endpoint == 'offline.resolve_conflict')
        if not allowed:
            return jsonify(error='Use the central server for deletion, user-security changes, credit and electronic payments.'), 403
    from .offline_catalog import ROUTES
    editing = request.endpoint in ROUTES
    if editing or request.endpoint in ('api.create_order', 'api.create_session', 'api.open_session', 'api.close_session'):
        if request.endpoint == 'api.create_order':
            from collections import Counter
            from ..models.product_product import ProductProduct
            from .offline_server import _finite
            try:
                data = request.get_json() or {}
                quantities = Counter()
                for line in data.get('lines', []):
                    qty, price, discount = (_finite(line.get('qty')), _finite(line.get('price_unit')),
                                            _finite(line.get('discount', 0)))
                    if qty <= 0 or price < 0 or not 0 <= discount <= 100:
                        raise SyncError('Invalid sale line.')
                    quantities[line['product_id']] += qty
                if not quantities:
                    raise SyncError('A sale must contain products.')
                products = {p.id: p for p in ProductProduct.browse(list(quantities))}
                if any(pid not in products or not products[pid].active or qty > (products[pid].available_qty or 0)
                       for pid, qty in quantities.items()):
                    raise SyncError('Insufficient local stock.')
            except (SyncError, TypeError, ValueError, KeyError, AttributeError) as error:
                return jsonify(error=str(error) if isinstance(error, SyncError) else 'Invalid sale.'), 400
        transaction = atomic()
        transaction.__enter__()
        g.offline_transaction = transaction
        if editing:
            from .offline_catalog import ensure_existing_maps, permission, project, revision, validate_values
            from ..odoo_orm import env, Many2one, Many2many
            model, argument = ROUTES[request.endpoint]
            creating = argument is None
            if not role_has_permission(g.user_role, permission(model, creating)):
                return jsonify(error='Your role cannot make this change.'), 403
            try:
                ensure_existing_maps()
                values = request.get_json(silent=True) or {}
                if not isinstance(values, dict):
                    raise SyncError('A JSON object is required.')
                if argument == 'ids':
                    ids = values.get('ids', [])
                elif argument == 'config':
                    ids = [r.id for r in env[model].search([('active', '=', True)], limit=1)]
                elif argument == 'company':
                    ids = [r.id for r in env[model].search([], limit=1)]
                elif argument:
                    ids = [(request.view_args or {}).get(argument) or request.args.get(argument, type=int)]
                else:
                    ids = []
                if argument in ('config', 'company') and not ids:
                    raise SyncError('Configure the company and POS on the central server before editing them offline.', 409)
                if any(type(item) is not int or item <= 0 for item in ids):
                    raise SyncError('Invalid record IDs.')
                version = values.pop('offline_revision', None)
                patch = {name: value for name, value in values.items() if name not in ('id', 'ids', 'currency')}
                if patch:
                    validate_values(model, patch)
                for name, value in patch.items():
                    field = env[model]._fields[name]
                    if isinstance(field, (Many2one, Many2many)):
                        targets = value if isinstance(field, Many2many) else ([value] if value else [])
                        if (not isinstance(targets, list) or any(type(item) is not int or item <= 0 for item in targets)
                                or len(env[field.comodel_name].browse(targets)) != len(set(targets))):
                            raise SyncError('Invalid catalogue relationship.')
                if (model == 'product.product' and not creating and 'cost_price' in patch
                        and any(not store.get('meta', f'catalog-cost-known:{key}') for key in ids)):
                    raise SyncError('Connect and synchronize with a manager account before editing an unknown purchase cost.', 409)
                before = {key: project(model, env[model].browse(key)[0]) for key in ids if env[model].browse(key)}
                if version and any(revision(model, env[model].browse(key)[0]) != version for key in before):
                    raise SyncError('This product changed while its form was open. Reload it before saving.', 409)
                g.offline_edit = {'model': model, 'before': before, 'ids': list(before), 'creating': creating}
            except (SyncError, TypeError, ValueError, KeyError, AttributeError) as error:
                return jsonify(error=str(error) if isinstance(error, SyncError) else 'Invalid business setting.'), getattr(error, 'status', 400)


def after_request(response):
    transaction = g.pop('offline_transaction', None)
    if transaction is None:
        return decorate_products(response)
    data = response.get_json(silent=True) or {}
    if response.status_code >= 400 or not data.get('success'):
        transaction.__exit__(Rollback, Rollback(), None)
        return response
    try:
        edit = g.pop('offline_edit', None)
        if edit:
            from .offline_client import capture_change
            ids = [(data.get('data') or {})['id']] if edit['creating'] else edit['ids']
            capture_change(edit['model'], edit['before'], ids, edit['creating'], g.user_id)
        else:
            from .offline_client import capture
            kind = 'sale' if request.endpoint == 'api.create_order' else 'session'
            result = data.get('data') or {}
            record_id = result.get('id') or (request.view_args or {}).get('session_id')
            record = capture(kind, record_id, g.user_id)
            if isinstance(data.get('data'), dict):
                data['data']['name'] = record.name
                response.set_data(json.dumps(data))
    except Exception as error:
        transaction.__exit__(type(error), error, error.__traceback__)
        failure = jsonify(success=False, error=str(error) if isinstance(error, SyncError)
                          else 'The operation was not saved. Please try again.')
        failure.status_code = 400
        return failure
    try:
        transaction.__exit__(None, None, None)
    except Exception:
        failure = jsonify(success=False, error='The sale was not saved. Please try again.')
        failure.status_code = 503
        return failure
    return decorate_products(response)


def decorate_products(response):
    endpoints = ('api.get_products', 'api.get_product', 'api.create_product',
                 'api.update_product', 'api.bulk_update_products')
    if store.local_mode() and request.endpoint in endpoints:
        from ..permissions import role_has_permission
        from ..models.product_product import ProductProduct
        from .offline_catalog import revision
        result = response.get_json(silent=True)
        if result and result.get('success'):
            rows = result['data'] if isinstance(result['data'], list) else [result['data']]
            for row in rows:
                if not role_has_permission(getattr(g, 'user_role', ''), 'product.write'):
                    row.pop('cost_price', None)
                else:
                    row['offline_cost_known'] = bool(store.get('meta', f'catalog-cost-known:{row["id"]}'))
                    records = ProductProduct.browse(row['id'])
                    if records:
                        row['offline_revision'] = revision('product.product', records[0])
            response.set_data(json.dumps(result))
    return response


def teardown():
    transaction = g.pop('offline_transaction', None)
    if transaction:
        transaction.__exit__(Rollback, Rollback(), None)
