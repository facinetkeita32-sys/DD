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
    if _initialized:
        return
    _initialized = True
    try:
        has_data = False
        for tname, tdata in _db_cache.items():
            if tdata['_data'] and tname not in ('sqlite_sequence',):
                has_data = True
                break
        print('INIT: _initialized=True, has_data={}'.format(has_data), flush=True)
        if not has_data:
            print('INIT: cache empty, loading demo data...', flush=True)
            load_demo_data()
            prod_count = len(_db_cache.get('product.product', {}).get('_data', {}))
            print('INIT: after load_demo_data, product.product has {} records in cache'.format(prod_count), flush=True)
            from . import odoo_orm
            odoo_orm._cache_loaded = False
            print('INIT: reset _cache_loaded, calling _load_cache() again', flush=True)
            _load_cache()
            prod_count2 = len(_db_cache.get('product.product', {}).get('_data', {}))
            print('INIT: after 2nd _load_cache, product.product has {} records in cache'.format(prod_count2), flush=True)
        else:
            prod_count = len(_db_cache.get('product.product', {}).get('_data', {}))
            print('INIT: cache already has data, product.product has {} records'.format(prod_count), flush=True)
        lot_start = time.time()
        StockLot()._init_defaults()
        lot_elapsed = time.time() - lot_start
        if lot_elapsed > 0.5:
            print('StockLot._init_defaults took {:.2f}s'.format(lot_elapsed), flush=True)
    except Exception:
        import traceback
        traceback.print_exc()
        _initialized = False


@app.before_request
def before_request():
    # Only load DB cache for API requests
    if request.path.startswith('/api/'):
        try:
            print('BEFORE_REQ: _load_cache() start', flush=True)
            _load_cache()
            print('BEFORE_REQ: _load_cache() done', flush=True)
            print('BEFORE_REQ: _ensure_initialized() start', flush=True)
            _ensure_initialized()
            print('BEFORE_REQ: _ensure_initialized() done', flush=True)
            prod_count = len(_db_cache.get('product.product', {}).get('_data', {}))
            print('BEFORE_REQ: product.product has {} records in cache'.format(prod_count), flush=True)
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
