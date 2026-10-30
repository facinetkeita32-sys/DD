"""
Shop With DD POS - Desktop App Launcher

Runs the Flask backend and opens it in a native window using pywebview.
Falls back to the default browser if pywebview is not available.
"""
import sys
import os
import threading
import time
import socket
import webbrowser
import signal
import hashlib
import secrets
from pathlib import Path

PORT = None
_instance_lock = None


def configure_offline():
    global _instance_lock
    base = Path(os.environ.get('POS_OFFLINE_DATA_DIR') or
                str(Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.local' / 'share')
                    / 'ShopWithDD' / 'OfflinePOS'))
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    _instance_lock = open(base / 'terminal.lock', 'a+b')
    try:
        # Do not read the locked byte: Windows rejects that read before a
        # second instance can report a friendly "already running" message.
        _instance_lock.seek(0, os.SEEK_END)
        if _instance_lock.tell() == 0:
            _instance_lock.write(b'1')
            _instance_lock.flush()
        _instance_lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(_instance_lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(_instance_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        _instance_lock.close()
        _instance_lock = None
        raise RuntimeError('This offline terminal is already running.')
    keyfile = base / 'session.key'
    if not keyfile.exists():
        fd = os.open(str(keyfile), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as output:
            output.write(secrets.token_hex(32))
    os.environ['SECRET_KEY'] = keyfile.read_text().strip()
    os.environ['DATABASE_URL'] = ''
    os.environ['POS_OFFLINE_MODE'] = '1'
    os.environ['DB_PATH'] = str(base / 'terminal.db')
    os.environ['OFFLINE_COOKIE_NAME'] = 'shopdd_' + hashlib.sha256(str(base.resolve()).encode()).hexdigest()[:12]
    return os.environ['DB_PATH']


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def start_server(port):
    from pos_system.main import app
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False)


def wait_for_server(port, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)
    return False


def open_browser(port):
    webbrowser.open(f'http://127.0.0.1:{port}')


def main():
    global PORT
    PORT = find_free_port()

    db_path = configure_offline()

    t = threading.Thread(target=start_server, args=(PORT,), daemon=True)
    t.start()

    if not wait_for_server(PORT):
        print("ERROR: Server failed to start")
        sys.exit(1)

    print(f"  Server: http://127.0.0.1:{PORT}")
    print("  Register this terminal with your server account before the first login.")
    print(f"  DB:     {db_path}")
    print("=" * 60)

    try:
        import webview
        webview.create_window(
            "Shop With DD POS",
            f"http://127.0.0.1:{PORT}",
            width=1280,
            height=860,
            resizable=True,
            min_size=(800, 600),
        )
        webview.start()
    except ImportError:
        print("  pywebview not installed, opening in browser...")
        open_browser(PORT)
        print("  Press Ctrl+C to stop the server")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down...")
            sys.exit(0)


if __name__ == '__main__':
    print("=" * 60)
    print("  Shop With DD POS")
    print("  Desktop App")
    print("=" * 60)
    main()
