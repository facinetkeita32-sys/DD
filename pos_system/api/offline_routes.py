import threading
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
    return success(conflicts_for(g.user))


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
