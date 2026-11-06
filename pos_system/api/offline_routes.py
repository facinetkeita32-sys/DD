import threading
import hmac
import time
import uuid
from flask import Blueprint, jsonify, request, session, g

from ..services import offline_store as store
from ..services.offline_server import SyncError
from ..models.res_users import ResUsers
from .routes import login_required

offline_bp = Blueprint('offline', __name__, url_prefix='/api/offline')


@offline_bp.errorhandler(SyncError)
def sync_error(error):
    response = jsonify(success=False, error=str(error), code=error.code, details=error.details)
    response.status_code = error.status
    response.headers['Cache-Control'] = 'no-store'
    return response


def success(data):
    response = jsonify(success=True, data=data)
    response.headers['Cache-Control'] = 'no-store'
    return response


def body():
    value = request.get_json() or {}
    if not isinstance(value, dict):
        raise SyncError('A JSON object is required.')
    return value


def server_device():
    if not store.enabled() or store.local_mode():
        raise SyncError('Synchronization is not enabled on this server.', 404, 'disabled')
    from ..services.offline_server import device
    identity = {'server_id': request.headers.get('X-POS-Server'), 'epoch': request.headers.get('X-POS-Epoch')}
    return device(request.headers.get('Authorization'), identity)


@offline_bp.get('/status')
def status():
    result = {'local': store.local_mode(), 'enabled': store.enabled()}
    if store.local_mode():
        from ..services.offline_client import config, pending
        settings = config()
        result['ready'] = bool(settings)
        if settings and session.get('user_id'):
            users = ResUsers.browse(session['user_id'])
            is_manager = users and users[0].role in ('admin', 'manager')
            result.update({key: settings.get(key) for key in ('connected', 'blocked', 'last_sync', 'error', 'device_name', 'server_url')})
            result['pending'] = sum(is_manager or row['user_id'] == session['user_id'] for _, row in pending())
    return success(result)


@offline_bp.post('/enroll')
def enroll():
    if not store.local_mode():
        raise SyncError('This endpoint is local only.', 404)
    from ..services.offline_client import enroll, NetworkUnavailable
    try:
        return success(enroll(body()))
    except NetworkUnavailable as e:
        raise SyncError(str(e), 503, 'network') from e


@offline_bp.post('/register')
def register():
    if not store.enabled() or store.local_mode():
        raise SyncError('Synchronization is not enabled on this server.', 404, 'disabled')
    from ..services.offline_server import register
    return success(register(body()))


@offline_bp.post('/authorize')
def authorize():
    from ..services.offline_server import credential_user, issue_grant
    from ..services.unit_of_work import atomic
    key, _ = server_device()
    data = body()
    user = credential_user(data.get('login'), data.get('password'))
    with atomic():
        return success(issue_grant(key, user))


@offline_bp.get('/catalogue')
def catalogue():
    from ..services.offline_server import catalogue
    key, _ = server_device()
    grant = {'id': request.headers.get('X-POS-User-Grant'), 'token': request.headers.get('X-POS-User-Token')}
    return success(catalogue(key, grant))


@offline_bp.post('/push')
def push():
    from ..services.offline_server import apply_operation
    key, row = server_device()
    return success(apply_operation(key, row, body().get('operation')))


@offline_bp.post('/receipt-email')
def receipt_email():
    """Send only a server-acknowledged order from the authenticated device."""
    from ..permissions import role_has_screen
    from ..services.offline_server import digest
    from ..services.receipt_service import get_order_data, build_share_text, generate_receipt_pdf
    from ..services.email_service import send_receipt_email
    from ..odoo_orm import _db_lock
    key, _ = server_device()
    data = body()
    try:
        operation_id = str(uuid.UUID(data['sale_operation_id']))
        grant_data = data['grant']
        grant = store.get('grants', grant_data['id'])
        if (not grant or grant['device_id'] != key or grant['epoch'] != store.get('meta', 'identity')['epoch']
                or grant['expires_at'] < time.time()
                or not hmac.compare_digest(grant['token_digest'], digest(grant_data['token']))):
            raise SyncError('User authorization is invalid or expired.', 403, 'receipt_access')
        users = ResUsers.browse(grant['user_id'])
        if not users or not users[0].active or not role_has_screen(users[0].role, 'orders'):
            raise SyncError('Receipt access is not authorized.', 403, 'receipt_access')
        applied = store.get('applied', operation_id)
        receipt = applied.get('receipt', {}) if applied else {}
        if (not applied or applied.get('device_id') != key or receipt.get('kind') != 'sale'
                or receipt.get('id') != operation_id or type(receipt.get('server_id')) is not int):
            raise SyncError('The synchronized order could not be verified.', 404, 'receipt_pending')
        order_id = receipt['server_id']
        order = get_order_data(order_id)
        if not order or (users[0].role == 'cashier' and order['_data'].get('user_id') != users[0].id):
            raise SyncError('Receipt not found or access denied.', 403, 'receipt_access')
        address = data.get('email')
        if (not isinstance(address, str) or not address.strip() or '@' not in address
                or len(address) > 254 or '\r' in address or '\n' in address):
            raise SyncError('Customer email is required.', 400, 'receipt_address')
        address = address.strip()
        lang = data.get('lang') if data.get('lang') in ('en', 'fr') else 'en'
        text = build_share_text(order_id, lang=lang)
        pdf = generate_receipt_pdf(order_id, lang=lang)
        if not text or not pdf:
            raise SyncError('Receipt could not be prepared.', 500, 'receipt_prepare')
        # Order reference may be user-edited: avoid header injection.
        reference = str(order['_data'].get('name') or order_id).replace('\r', '').replace('\n', '')
    except SyncError:
        raise
    except (KeyError, AttributeError, TypeError, ValueError) as error:
        raise SyncError('Invalid receipt request.', 400, 'receipt_invalid') from error
    if g.pop('db_lock_held', False):
        _db_lock.release()
    ok, _message = send_receipt_email(address, f'Receipt {reference}', text,
                                      pdf_bytes=pdf, filename='receipt.pdf')
    if not ok:
        raise SyncError('Email delivery could not be confirmed. Check server email settings and recipient before retrying.',
                        502, 'receipt_delivery_unknown')
    return success({'message': 'Receipt sent successfully.'})


@offline_bp.post('/sync')
@login_required
def sync_now():
    if not store.local_mode():
        raise SyncError('This endpoint is local only.', 404)
    from ..services.offline_client import synchronize
    threading.Thread(target=synchronize, daemon=True).start()
    return success({'scheduled': True})


@offline_bp.get('/conflicts')
@login_required
def conflicts():
    if not store.local_mode():
        raise SyncError('This endpoint is local only.', 404)
    from ..services.offline_catalog import conflicts_for
    result = conflicts_for(g.user)
    if g.user_role in ('admin', 'manager'):
        for key, row in store.all_rows('outbox'):
            if row.get('status') == 'conflict' and row['operation'].get('kind') == 'payment':
                result.append({'id': key, 'kind': 'payment', 'local_id': row['local_id'],
                               'amount': row['operation']['data'].get('amount'),
                               'server': row.get('conflict', {})})
    return success(result)


@offline_bp.post('/conflicts/<operation_id>/resolve')
@login_required
def resolve_conflict(operation_id):
    if not store.local_mode():
        raise SyncError('This endpoint is local only.', 404)
    from ..services.offline_catalog import resolve_conflict
    from ..services.unit_of_work import atomic
    data = body()
    with atomic():
        resolve_conflict(operation_id, data.get('decision'), data.get('values', {}), g.user)
    return success({'queued': True})


@offline_bp.post('/conflicts/<operation_id>/retry-payment')
@login_required
def retry_payment_conflict(operation_id):
    """Retry the original immutable payment, never delete or replace it."""
    if not store.local_mode():
        raise SyncError('This endpoint is local only.', 404)
    if g.user_role not in ('admin', 'manager'):
        raise SyncError('Only a manager can review payment conflicts.', 403, 'permission')
    from ..services.offline_client import config, pending, synchronize
    from ..services.unit_of_work import atomic
    try:
        key = str(uuid.UUID(operation_id))
    except (ValueError, TypeError, AttributeError) as error:
        raise SyncError('Invalid payment conflict.', 400) from error
    with atomic():
        settings = config()
        queue = pending()
        if not settings or settings.get('blocked'):
            raise SyncError('Terminal authorization must be resolved first.', 409, 'grant')
        if not queue or queue[0][0] != key:
            raise SyncError('Only the first pending operation can be retried.', 409, 'conflict')
        row = queue[0][1]
        if row.get('status') != 'conflict' or row.get('operation', {}).get('kind') != 'payment':
            raise SyncError('Payment conflict not found.', 404)
        row['status'] = 'pending'
        store.put('outbox', key, row)
        settings['error'] = None
        store.put('meta', 'client', settings)
    threading.Thread(target=synchronize, daemon=True).start()
    return success({'scheduled': True})


@offline_bp.get('/devices')
@login_required
def devices():
    if not store.enabled() or store.local_mode() or g.user_role not in ('admin', 'manager'):
        raise SyncError('Device management is not authorized.', 403)
    return success([dict(id=key, **{field: row.get(field) for field in ('name', 'active', 'registered_at')})
                    for key, row in store.all_rows('devices')
                    if g.user_role == 'admin' or row['owner_id'] == g.user_id])


@offline_bp.post('/devices/<device_id>/revoke')
@login_required
def revoke(device_id):
    if not store.enabled() or store.local_mode() or g.user_role not in ('admin', 'manager'):
        raise SyncError('Device management is not authorized.', 403)
    row = store.get('devices', device_id)
    if not row or (g.user_role != 'admin' and row['owner_id'] != g.user_id):
        raise SyncError('Terminal not found.', 404)
    row['active'] = False
    store.put('devices', device_id, row)
    return success({'revoked': True})
