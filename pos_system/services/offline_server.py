"""Opt-in, single-business device API. All sale acknowledgements are atomic."""
import hashlib
import copy
import hmac
import json
import math
import secrets
import time
import uuid
from collections import Counter

from werkzeug.security import check_password_hash

from ..models.res_users import ResUsers
from ..models.res_company import ResCompany
from ..models.pos_config import PosConfig
from ..models.pos_order import PosOrder
from ..models.pos_order_line import PosOrderLine
from ..models.pos_payment import PosPayment
from ..models.pos_payment_method import PosPaymentMethod
from ..models.pos_session import PosSession
from ..models.product_product import ProductProduct
from ..models.res_partner import ResPartner
from ..permissions import role_has_permission
from . import offline_store as store
from .backup_service import _registry, _read_rows, _json_value
from .unit_of_work import atomic
from .. import db

REFERENCE_MODELS = {
    'res.lang', 'res.currency', 'res.company', 'pos.config', 'product.category',
    'pos.category', 'pos.payment.method', 'pos.tax', 'delivery.zone',
    'product.product', 'res.partner',
}


class SyncError(ValueError):
    def __init__(self, message, status=400, code='invalid', details=None):
        super().__init__(message)
        self.status, self.code = status, code
        self.details = details


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def credential_user(login, password):
    if not isinstance(login, str) or not isinstance(password, str):
        raise SyncError('Invalid credentials', 401, 'credentials')
    users = ResUsers.search([('login', '=', login), ('active', '=', True)], limit=1)
    valid = False
    if users:
        stored = users[0]._data.get('password') or ''
        valid = (check_password_hash(stored, password) if stored.startswith(('scrypt:', 'pbkdf2:'))
                 else hmac.compare_digest(stored.encode(), password.encode()))
    if not valid:
        raise SyncError('Invalid credentials', 401, 'credentials')
    return users[0]


def public_user(user):
    return dict(id=user.id, **{key: user._data.get(key) for key in
                              ('login', 'name', 'role', 'lang', 'active')})


def single_company():
    companies = ResCompany.search([])
    configs = PosConfig.search([('active', '=', True)])
    ids = {company.id for company in companies}
    ids.update(c._data['company_id'] for c in configs if c._data.get('company_id'))
    currencies = {c._data['currency_id'] for c in configs if c._data.get('currency_id')}
    if len(ids) > 1 or len(currencies) > 1:
        raise SyncError('Offline sync requires one unambiguous company and currency.', 409, 'scope')
    return next(iter(ids), None)


def issue_grant(device_id, user):
    if not role_has_permission(user.role, 'order.create'):
        raise SyncError('This account cannot use an offline POS.', 403, 'permission')
    now = time.time()
    key, secret = str(uuid.uuid4()), secrets.token_urlsafe(32)
    grant = {'id': key, 'device_id': device_id, 'user_id': user.id, 'issued_at': now,
             'expires_at': now + 7 * 86400, 'epoch': store.get('meta', 'identity')['epoch']}
    store.put('grants', key, dict(grant, token_digest=digest(secret)))
    return dict(grant, token=secret, user=public_user(user))


def register(body):
    user = credential_user(body.get('login'), body.get('password'))
    if user._data.get('role') not in ('admin', 'manager'):
        raise SyncError('A manager must register this terminal.', 403, 'permission')
    company_id = single_company()
    name = body.get('device_name', '')
    if not isinstance(name, str) or not name.strip() or len(name) > 100:
        raise SyncError('A terminal name is required.')
    key, secret = str(uuid.uuid4()), secrets.token_urlsafe(48)
    with atomic():
        store.put('devices', key, {'name': name.strip(), 'owner_id': user.id,
                                  'company_id': company_id, 'token_digest': digest(secret),
                                  'active': True, 'registered_at': time.time()})
        grant = issue_grant(key, user)
    return {'device_id': key, 'credential': key + '.' + secret,
            **store.get('meta', 'identity'), 'grant': grant}


def device(authorization, identity=None):
    try:
        key, secret = authorization.removeprefix('Bearer ').split('.', 1)
    except (ValueError, AttributeError):
        raise SyncError('Device authentication required.', 401, 'device')
    row = store.get('devices', key)
    if not row or not row.get('active') or not hmac.compare_digest(row['token_digest'], digest(secret)):
        raise SyncError('This terminal is not authorized.', 401, 'revoked')
    owners = ResUsers.browse(row['owner_id'])
    if not owners or not owners[0].active or owners[0].role not in ('admin', 'manager'):
        raise SyncError('Terminal registration must be renewed by a manager.', 403, 'revoked')
    if single_company() != row.get('company_id'):
        raise SyncError('Terminal company scope changed.', 409, 'scope')
    current = store.get('meta', 'identity')
    if identity and any(identity.get(field) != current[field] for field in ('server_id', 'epoch')):
        raise SyncError('Server recovery detected. Keep pending sales and contact a manager.', 409, 'epoch')
    return key, row


def catalogue(device_id, management_grant=None):
    models, relations = _registry()
    selected = set(REFERENCE_MODELS)
    for name in relations:
        if any(name.startswith(model + '_') for model in REFERENCE_MODELS):
            selected.add(name)
    # Never send credentials, user tables, server sales, logs or backup API keys.
    conn = db.get_conn()
    try:
        tables = {name: [{key: _json_value(value) for key, value in row.items()}
                         for row in _read_rows(conn, name)] for name in sorted(selected)}
    finally:
        conn.close()
    management = None
    if management_grant and management_grant.get('id') and management_grant.get('token'):
        grant = store.get('grants', management_grant['id'])
        if (grant and grant['device_id'] == device_id and grant['expires_at'] > time.time()
                and grant['epoch'] == store.get('meta', 'identity')['epoch']
                and hmac.compare_digest(grant['token_digest'], digest(management_grant['token']))):
            records = ResUsers.browse(grant['user_id'])
            if records and records[0].active and role_has_permission(records[0].role, 'product.write'):
                management = records[0]
    if management is None:
        for row in tables.get('product.product', []):
            row.pop('cost_price', None)
    users = {}
    for _, grant in store.all_rows('grants'):
        if grant['device_id'] == device_id:
            records = ResUsers.browse(grant['user_id'])
            if records:
                users[str(records[0].id)] = public_user(records[0])
            else:
                users[str(grant['user_id'])] = {'id': grant['user_id'], 'active': False}
    return {'tables': tables, 'users': list(users.values()),
            **store.get('meta', 'identity'), 'server_time': time.time()}


def _finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise SyncError('Invalid numeric value.')
    return value


def _resource(device_id, kind, key):
    uuid.UUID(key)
    return f'resource:{device_id}:{kind}:{key}'


def _session(device_id, payload, user):
    key = _resource(device_id, 'session', payload['uuid'])
    mapping = store.get('applied', key)
    allowed = ('name', 'state', 'start_at', 'stop_at', 'cash_register_balance_start',
               'cash_register_balance_end')
    values = {field: payload.get(field) for field in allowed}
    if values['state'] not in ('opening_control', 'opened', 'closed'):
        raise SyncError('Invalid session state.')
    for field in ('cash_register_balance_start', 'cash_register_balance_end'):
        values[field] = _finite(values[field] or 0)
    values['name'] = 'OFF-' + device_id[:8] + '-' + payload['uuid']
    if mapping:
        records = PosSession.browse(mapping['server_id'])
        if not records or records[0]._data.get('user_id') != user.id:
            raise SyncError('Session mapping requires reconciliation.', 409, 'conflict')
        record = records[0]
        record.write(values)
    else:
        record = PosSession.create(dict(values, user_id=user.id))
        store.put('applied', key, {'server_id': record.id})
    if values['state'] == 'closed':
        record.action_close()
        record.write({'stop_at': values['stop_at']})
    return record.id


def _sale(device_id, payload, user, company_id):
    from .offline_catalog import resolve
    payload = copy.deepcopy(payload)
    for line in payload.get('lines', []):
        if 'product_ref' in line:
            line['product_id'] = resolve(device_id, 'product.product', line['product_ref'])
        if 'tax_refs' in line:
            line['tax_ids'] = [resolve(device_id, 'pos.tax', ref) for ref in line['tax_refs']]
    for payment in payload.get('payments', []):
        if 'method_ref' in payment:
            payment['payment_method_id'] = resolve(device_id, 'pos.payment.method', payment['method_ref'])
    if 'customer_ref' in payload:
        payload['partner_id'] = resolve(device_id, 'res.partner', payload['customer_ref'])
    if 'delivery_ref' in payload:
        payload['delivery_zone_id'] = resolve(device_id, 'delivery.zone', payload['delivery_ref'])
    lines, payments = payload.get('lines'), payload.get('payments')
    if not isinstance(lines, list) or not lines or len(lines) > 500 or not isinstance(payments, list) or not payments:
        raise SyncError('A sale must contain lines and payments.')
    quantities, total = Counter(), 0
    for line in lines:
        qty, price, discount = (_finite(line.get('qty')), _finite(line.get('price_unit')),
                                _finite(line.get('discount', 0)))
        if qty <= 0 or price < 0 or not 0 <= discount <= 100:
            raise SyncError('Invalid sale line.')
        subtotal = qty * price - qty * price * discount / 100
        if abs(subtotal - _finite(line.get('price_subtotal'))) > .000001:
            raise SyncError('Sale line totals do not match.')
        total += subtotal
        quantities[line['product_id']] += qty
    products = {p.id: p for p in ProductProduct.browse(list(quantities))}
    for pid, qty in quantities.items():
        if pid not in products or not products[pid].active or (products[pid].available_qty or 0) < qty:
            raise SyncError('Stock or product conflict; the local sale remains safely queued.', 409, 'conflict')
    delivery = _finite(payload.get('delivery_cost', 0))
    if delivery < 0:
        raise SyncError('Invalid delivery amount.')
    total += delivery
    if abs(total - _finite(payload.get('amount_total'))) > .000001:
        raise SyncError('Sale totals do not match.')
    paid = 0
    for payment in payments:
        methods = PosPaymentMethod.browse(payment.get('payment_method_id', 0))
        if not methods or not methods[0].active:
            raise SyncError('The recorded payment method is unavailable; the sale remains queued.', 409, 'conflict')
        amount = _finite(payment.get('amount'))
        if amount < 0:
            raise SyncError('Invalid payment amount.')
        paid += amount
    if paid < total - .01 or abs(paid - _finite(payload.get('amount_paid'))) > .000001:
        raise SyncError('Offline sales must be fully paid.')
    customer = payload.get('partner_id') or False
    if customer and not ResPartner.browse(customer):
        raise SyncError('Customer requires reconciliation.', 409, 'conflict')
    session_id = False
    if payload.get('session_uuid'):
        mapping = store.get('applied', _resource(device_id, 'session', payload['session_uuid']))
        records = PosSession.browse(mapping['server_id']) if mapping else []
        if not records or records[0]._data.get('user_id') != user.id or records[0].state != 'opened':
            raise SyncError('Cashier session must synchronize first.', 409, 'conflict')
        session_id = records[0].id
    name = 'OFF-' + device_id[:8] + '-' + payload['uuid']
    from ..models.pos_tax import PosTax
    for line in lines:
        tax_ids = line.get('tax_ids') or []
        if (not isinstance(tax_ids, list) or any(type(tid) is not int for tid in tax_ids)
                or len(PosTax.browse(tax_ids)) != len(set(tax_ids))):
            raise SyncError('Tax configuration requires reconciliation.', 409, 'conflict')
    values = {key: payload.get(key) for key in ('date_order', 'note', 'delivery_contact_name', 'delivery_contact_phone', 'delivery_zone_id')}
    values['amount_tax'] = _finite(payload.get('amount_tax', 0))
    values.update(name=name, pos_reference=name, user_id=user.id, company_id=company_id,
                  session_id=session_id, partner_id=customer, delivery_cost=delivery,
                  amount_total=total, amount_paid=paid, amount_change=max(0, paid - total), state='paid')
    record = PosOrder.create(values)
    for line in lines:
        fields = ('product_id', 'product_name', 'qty', 'price_unit', 'discount', 'price_subtotal')
        PosOrderLine.create(dict({field: line.get(field) for field in fields}, order_id=record.id,
                                 tax_ids=line.get('tax_ids') or []))
    for payment in payments:
        PosPayment.create({'order_id': record.id, 'payment_method_id': payment['payment_method_id'],
                           'amount': payment['amount'], 'payment_date': payment.get('payment_date'),
                           'reference': payment.get('reference') or ''})
    for pid, qty in quantities.items():
        products[pid].write({'available_qty': max(0, products[pid].available_qty - qty)})
    return record.id


def apply_operation(device_id, device_row, operation):
    if not isinstance(operation, dict):
        raise SyncError('Invalid operation.')
    try:
        key = str(uuid.UUID(operation['id']))
        payload = operation['data']
        uuid.UUID(payload['uuid'])
        kind = operation['kind']
        if kind not in ('sale', 'session', 'catalog'):
            raise SyncError('Unsupported operation.')
        fingerprint = digest(json.dumps(operation, sort_keys=True, separators=(',', ':')))
        with atomic():
            previous = store.get('applied', key)
            if previous:
                if previous.get('device_id') != device_id or previous.get('digest') != fingerprint:
                    raise SyncError('An operation ID was reused with different contents.', 409, 'conflict')
                return previous['receipt']
            grant = store.get('grants', operation['grant']['id'])
            if (not grant or grant['device_id'] != device_id
                    or grant['epoch'] != store.get('meta', 'identity')['epoch']
                    or not hmac.compare_digest(grant['token_digest'], digest(operation['grant']['token']))):
                raise SyncError('Cashier authorization is invalid.', 403, 'grant')
            created = _finite(operation.get('created_at'))
            if not grant['issued_at'] - 300 <= created <= grant['expires_at'] or created > time.time() + 300:
                raise SyncError('Sale was recorded outside offline authorization.', 403, 'grant')
            users = ResUsers.browse(grant['user_id'])
            if not users or not users[0].active or not role_has_permission(users[0].role, 'order.create'):
                raise SyncError('Cashier access was revoked; manager reconciliation is required.', 403, 'grant')
            resource = None
            if kind == 'catalog':
                from .offline_catalog import apply_change
                resource = apply_change(device_id, payload, users[0])
                server_id = resource['server_id']
            else:
                server_id = (_sale(device_id, payload, users[0], device_row.get('company_id'))
                             if kind == 'sale' else _session(device_id, payload, users[0]))
            receipt = {'id': key, 'server_id': server_id, 'kind': kind}
            if resource:
                receipt['resource'] = resource
            store.put('applied', key, {'device_id': device_id, 'digest': fingerprint, 'receipt': receipt})
            return receipt
    except SyncError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as e:
        raise SyncError('Incomplete operation.') from e
