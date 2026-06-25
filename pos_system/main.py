import os
import sys
import time
from flask import Flask, send_from_directory, request, g, session, jsonify
from .api.routes import api_bp
from .i18n import translator
from .init_data import load_demo_data
from .odoo_orm import _load_cache, _db_cache
from .models.stock_lot import StockLot

app = Flask(__name__, static_folder='static', static_url_path='')
app.secret_key = os.environ.get('SECRET_KEY', 'change-me-in-production')
SESSION_TIMEOUT = int(os.environ.get('SESSION_TIMEOUT', 7200))

app.register_blueprint(api_bp)


_initialized = False


def _ensure_initialized():
    global _initialized
    global _images_migrated
    if _initialized:
        return
    _initialized = True
    try:
        # Check if critical tables have data in cache
        need_demo = True
        for tbl in ('res.users', 'product.product', 'res.partner'):
            data = _db_cache.get(tbl, {}).get('_data', {})
            if data:
                need_demo = False
            else:
                need_demo = True
                break
        if need_demo:
            print('Cache missing critical data, loading demo data...', flush=True)
            load_demo_data()
            from . import odoo_orm
            odoo_orm._cache_loaded = False
            _load_cache()
            # Validate post-init cache has critical tables
            all_ok = True
            for tbl, label in [('res.users', 'users'), ('product.product', 'products'), ('res.partner', 'customers')]:
                cnt = len(_db_cache.get(tbl, {}).get('_data', {}))
                if cnt == 0:
                    print('WARN: {} table empty after init'.format(tbl), flush=True)
                    all_ok = False
                else:
                    print('{}: {} records loaded'.format(label, cnt), flush=True)
            if not all_ok:
                print('Cache still empty after demo data load, will retry on next request', flush=True)
                _initialized = False
                from . import odoo_orm
                odoo_orm._cache_loaded = False
                return
        lot_start = time.time()
        StockLot()._init_defaults()
        lot_elapsed = time.time() - lot_start
        if lot_elapsed > 0.5:
            print('StockLot._init_defaults took {:.2f}s'.format(lot_elapsed), flush=True)
        # One-time migration: existing base64 images to Supabase Storage
        if not _images_migrated:
            _images_migrated = True
            try:
                from .api.routes import migrate_product_images
                migrate_product_images()
            except Exception:
                import traceback
                traceback.print_exc()
    except Exception:
        import traceback
        traceback.print_exc()
        _initialized = False
        from . import odoo_orm
        odoo_orm._cache_loaded = False


@app.before_request
def before_request():
    if request.path.startswith('/api/'):
        try:
            _load_cache()
            _ensure_initialized()
        except Exception:
            print('WARN: _load_cache/_ensure_initialized failed, serving with current cache', flush=True)
            import traceback
            traceback.print_exc()
    # Session inactivity timeout
    if 'user_id' in session:
        last = session.get('last_activity', 0)
        if time.time() - last > SESSION_TIMEOUT:
            session.clear()
        else:
            session['last_activity'] = time.time()
    lang = session.get('lang', request.args.get('lang', 'en'))
    translator.set_language(lang)


@app.teardown_appcontext
def teardown(exception):
    try:
        conn = g.pop('_db_conn', None)
        if conn:
            from .odoo_orm import get_pool
            get_pool().putconn(conn)
    except Exception:
        pass


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/<path:path>')
def static_files(path):
    return send_from_directory(app.static_folder, path)


@app.errorhandler(404)
def not_found(e):
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Endpoint not found: %s' % request.path}), 404
    return send_from_directory(app.static_folder, 'index.html') if request.method == 'GET' else ('Not Found', 404)

@app.errorhandler(405)
def method_not_allowed(e):
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': 'Method not allowed: %s %s' % (request.method, request.path)}), 405
    return ('Method Not Allowed', 405)

@app.errorhandler(500)
def server_error(e):
    if request.path.startswith('/api/'):
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': 'Internal server error: %s' % str(e)}), 500
    return ('Server Error', 500)

@app.route('/api/translations/<lang>')
def get_translations(lang):
    translations = translator.get_translations(lang)
    return jsonify({'success': True, 'data': translations})


@app.route('/api/system/health')
def system_health():
    from .odoo_orm import _cache_loaded
    tables = {}
    for name, tbl in sorted(_db_cache.items()):
        if name in ('sqlite_sequence',):
            continue
        tables[name] = len(tbl.get('_data', {}))
    return jsonify({
        'success': True,
        'data': {
            'initialized': _initialized,
            'cache_loaded': _cache_loaded,
            'db_tables': tables,
        }
    })


def create_app():
    import traceback
    try:
        _load_cache()
        _ensure_initialized()
    except Exception:
        print('STARTUP ERROR:', flush=True)
        traceback.print_exc()
        print('App will start; init deferred to first request.', flush=True)
    return app


if __name__ == '__main__':
    create_app()
    print("=" * 60)
    print("  Shop With DD POS")
    print("  Multi-language: English / Français")
    print("  Currency: GNF (Guinean Franc)")
    print("  Database: PostgreSQL")
    print("=" * 60)
    print(f"  Server: http://0.0.0.0:5000")
    print(f"  Login:  admin / admin")
    print("=" * 60)
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host='0.0.0.0', port=5000, debug=debug)
