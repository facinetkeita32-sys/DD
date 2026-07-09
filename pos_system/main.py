import os
import sys
from flask import Flask, send_from_directory, request, g, session
from .api.routes import api_bp
from .api.backup_routes import backup_bp
from .i18n import translator
from .init_data import load_demo_data
from .odoo_orm import _load_cache, _db_cache, DB_PATH

app = Flask(__name__, static_folder='static', static_url_path='')
app.secret_key = os.environ.get('SECRET_KEY', 'pos-guinea-secret-key-change-in-production')

app.register_blueprint(api_bp)
app.register_blueprint(backup_bp)


@app.before_request
def before_request():
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
