import os
import sys
from flask import Flask, send_from_directory, request, g, session
from .api.routes import api_bp
from .api.backup_routes import backup_bp
from .i18n import translator
from .init_data import load_demo_data
from .odoo_orm import _load_cache, _db_cache

app = Flask(__name__, static_folder='static', static_url_path='')
app.secret_key = 'pos-guinea-secret-key-change-in-production'

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


if __name__ == '__main__':
    create_app()
    print("=" * 60)
    print("  Shop With DD POS")
    print("  Multi-language: English / Français")
    print("  Currency: GNF (Guinean Franc)")
    print("  Database: SQLite (pos_data.db)")
    print("=" * 60)
    print(f"  Server: http://localhost:5000")
    print(f"  Login:  admin / admin")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)
