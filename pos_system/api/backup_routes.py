import json
from flask import Blueprint, request, jsonify, session, Response, g
from ..services.backup_service import (
    export_full_backup,
    push_backup,
    save_backup_to_file,
    restore_from_data,
    get_backup_status,
    save_backup_settings,
)
from ..odoo_orm import env, _db_lock
from .routes import login_required

backup_bp = Blueprint('backup', __name__, url_prefix='/api/backup')


@backup_bp.route('/export', methods=['GET'])
@login_required
def handle_export():
    data = export_full_backup(env)
    return jsonify({'success': True, 'data': data})


@backup_bp.route('/download', methods=['GET'])
@login_required
def handle_download():
    data = export_full_backup(env)
    json_str = json.dumps(data, ensure_ascii=False, indent=2)
    return Response(
        json_str,
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment; filename=pos_backup.json'}
    )


@backup_bp.route('/push', methods=['POST'])
@login_required
def handle_push():
    body = request.get_json(force=True) or {}
    url = body.get('url', '').strip()
    if not url:
        return jsonify({'success': False, 'error': 'Backup URL is required'}), 400
    api_key = body.get('api_key', '').strip() or None
    try:
        data = export_full_backup(env)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 502
    # Authentication and the snapshot are complete. The upload only uses the
    # detached snapshot, so other API requests can proceed during network I/O.
    if g.pop('db_lock_held', False):
        _db_lock.release()
    result = push_backup(url, api_key, env, backup_data=data)
    if result['success']:
        return jsonify(result)
    return jsonify(result), 502


@backup_bp.route('/restore', methods=['POST'])
@login_required
def handle_restore():
    body = request.get_json(force=True) or {}
    data = body.get('data')
    if not data:
        return jsonify({'success': False, 'error': 'Backup data is required'}), 400
    result = restore_from_data(env, data)
    if result['success']:
        # The restored users/credentials may differ from the current session.
        session.clear()
        return jsonify(result)
    return jsonify(result), 400


@backup_bp.route('/status', methods=['GET'])
@login_required
def handle_status():
    return jsonify({'success': True, 'data': get_backup_status()})


@backup_bp.route('/settings', methods=['POST'])
@login_required
def handle_save_settings():
    body = request.get_json(force=True) or {}
    result = save_backup_settings(body, env)
    return jsonify(result), 200 if result['success'] else 400
