import os
import sys
import time
from flask import Flask, send_from_directory, request, g, session
from .api.routes import api_bp
from .i18n import translator
from .init_data import load_demo_data
from .odoo_orm import _load_cache, _db_cache
from .models.stock_lot import StockLot

app = Flask(__name__, static_folder='static', static_url_path='')
app.secret_key = os.environ.get('SECRET_KEY', 'change-me-in-production')
SESSION_TIMEOUT = int(os.environ.get('SESSION_TIMEOUT', 7200))

app.register_blueprint(api_bp)


@app.before_request
def before_request():
    _load_cache()
    # Session inactivity timeout
    if 'user_id' in session:
        last = session.get('last_activity', 0)
        if time.time() - last > SESSION_TIMEOUT:
            session.clear()
        else:
            session['last_activity'] = time.time()
    lang = session.get('lang', request.args.get('lang', 'en'))
    translator.set_language(lang)


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
    _load_cache()
    has_data = False
    for tname, tdata in _db_cache.items():
        if tdata['_data'] and tname not in ('sqlite_sequence',):
            has_data = True
            break
    if not has_data:
        load_demo_data()
    StockLot()._init_defaults()
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
