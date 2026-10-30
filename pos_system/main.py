import os
import sys
import time
from flask import Flask, send_from_directory, request, g, session
from .api.routes import api_bp
from .api.backup_routes import backup_bp
from .api.offline_routes import offline_bp
from .i18n import translator
from .init_data import load_demo_data
from .odoo_orm import _load_cache, _db_cache, _db_lock, DB_PATH
from .services.backup_service import load_backup_settings

app = Flask(__name__, static_folder='static', static_url_path='')
app.secret_key = os.environ.get('SECRET_KEY', 'pos-guinea-secret-key-change-in-production')
if os.environ.get('POS_OFFLINE_MODE') == '1':
    app.config['SESSION_COOKIE_NAME'] = os.environ.get('OFFLINE_COOKIE_NAME', 'shopdd_offline')
# Session inactivity timeout in seconds (default: 1 hour)
SESSION_TIMEOUT = int(os.environ.get('SESSION_TIMEOUT', 3600))

app.register_blueprint(api_bp)
app.register_blueprint(backup_bp)
app.register_blueprint(offline_bp)


@app.before_request
def before_request():
    # The ORM has a process-local cache. Hold a shared lock across each API
    # request so a restore cannot interleave with a sale or a background backup.
    # Backup uploads release it early once their detached snapshot is ready.
    if request.path.startswith('/api/'):
        _db_lock.acquire()
        g.db_lock_held = True
    from .services.offline_local import before_request as offline_before_request
    offline_response = offline_before_request()
    if offline_response is not None:
        return offline_response
    # Session inactivity timeout (API requests only)
    if request.path.startswith('/api/') and not request.path.startswith('/api/auth/login'):
        if 'user_id' in session:
            last = session.get('last_activity', 0)
            if time.time() - last > SESSION_TIMEOUT:
                session.clear()
                from flask import jsonify
                return jsonify({'error': 'Session expired due to inactivity'}), 401
            session['last_activity'] = time.time()
    lang = session.get('lang', request.args.get('lang', 'en'))
    translator.set_language(lang)


@app.teardown_request
def release_database_lock(error=None):
    from .services.offline_local import teardown
    teardown()
    if g.pop('db_lock_held', False):
        _db_lock.release()


@app.after_request
def finish_offline_transaction(response):
    from .services.offline_local import after_request
    return after_request(response)


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/<path:path>')
def static_files(path):
    return send_from_directory(app.static_folder, path)


@app.route('/api/translations/<lang>')
def get_translations(lang):
    from flask import jsonify
    translations = translator.get_translations(lang)
    return jsonify({'success': True, 'data': translations})


def create_app():
    from .services import offline_store
    from . import db
    if offline_store.local_mode() and db._use_pg:
        raise RuntimeError('Offline terminals require a separate local SQLite database.')
    offline_store.initialize()
    _load_cache()
    if (offline_store.local_mode() and not offline_store.get('meta', 'client')
            and any(table['_data'] for table in _db_cache.values())):
        raise RuntimeError('Refusing to provision over an existing business database. Use a fresh terminal folder.')
    has_data = False
    for tname, tdata in _db_cache.items():
        if tdata['_data'] and tname not in ('sqlite_sequence',):
            has_data = True
            break
    if not has_data and not offline_store.local_mode():
        load_demo_data()
    if not offline_store.local_mode():
        load_backup_settings()
    else:
        from .services.offline_client import start_worker
        start_worker()
    return app


# Initialize on import (required for gunicorn)
create_app()


if __name__ == '__main__':
    print("=" * 60)
    print("  Shop With DD POS")
    print("  Multi-language: English / Français")
    print("  Currency: GNF (Guinean Franc)")
    print("  Database: SQLite")
    print(f"  DB Path: {DB_PATH}")
    print("=" * 60)
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('DEBUG', 'true').lower() == 'true'
    print(f"  Server: http://{host}:{port}")
    print("  Login:  admin / admin")
    print("=" * 60)
    app.run(host=host, port=port, debug=debug)
