#!/usr/bin/env python
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pos_system.main import create_app, app

if __name__ == '__main__':
    create_app()
    print("=" * 60)
    print("  Shop With DD POS")
    print("  Multi-language: English / Français")
    print("  Currency: GNF (Guinean Franc)")
    print("=" * 60)
    print(f"  Open http://localhost:5000 in your browser")
    print(f"  Login:  admin / admin")
    print("=" * 60)
    app.run(host='0.0.0.0', port=5000, debug=True)
