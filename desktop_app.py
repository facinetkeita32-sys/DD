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

PORT = None


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def start_server(port):
    from pos_system.main import create_app
    app = create_app()
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

    # Determine DB path
    if getattr(sys, 'frozen', False):
        db_path = os.path.join(os.path.dirname(os.path.abspath(sys.executable)), 'pos_data.db')
    else:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pos_data.db')

    t = threading.Thread(target=start_server, args=(PORT,), daemon=True)
    t.start()

    if not wait_for_server(PORT):
        print("ERROR: Server failed to start")
        sys.exit(1)

    print(f"  Server: http://127.0.0.1:{PORT}")
    print(f"  Login:  admin / admin")
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
