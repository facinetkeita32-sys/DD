"""Launcher storage/locking checks without opening a window or using POS data."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DesktopLauncherTests(unittest.TestCase):
    def test_single_instance_lock_releases_and_session_key_survives_restart(self):
        root = Path(__file__).resolve().parents[1]
        configure = (
            'import desktop_app,os,json,hashlib; '
            'path=desktop_app.configure_offline(); '
            'print(json.dumps({"path":path,"mode":os.environ["POS_OFFLINE_MODE"],'
            '"database_url":os.environ["DATABASE_URL"],'
            '"key_hash":hashlib.sha256(os.environ["SECRET_KEY"].encode()).hexdigest()}),flush=True); '
        )
        with tempfile.TemporaryDirectory() as folder:
            environment = dict(os.environ, POS_OFFLINE_DATA_DIR=folder,
                               DATABASE_URL='must-not-connect-to-this-inherited-url')
            holder = subprocess.Popen([sys.executable, '-c', configure + 'input()'],
                                      cwd=root, env=environment, stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                line = holder.stdout.readline()
                self.assertTrue(line, 'First launcher did not initialize')
                first = json.loads(line)
                self.assertEqual('1', first['mode'])
                self.assertEqual('', first['database_url'])
                self.assertEqual(str(Path(folder) / 'terminal.db'), first['path'])
                second = subprocess.run([sys.executable, '-c', configure], cwd=root,
                                        env=environment, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(0, second.returncode)
                self.assertIn('This offline terminal is already running.', second.stderr)
            finally:
                if holder.poll() is None:
                    holder.communicate(input='close\n', timeout=10)
                holder.stdout.close()
                holder.stderr.close()
                holder.stdin.close()
            restarted = subprocess.run([sys.executable, '-c', configure], cwd=root,
                                       env=environment, capture_output=True, text=True, timeout=10)
            self.assertEqual(0, restarted.returncode, restarted.stderr)
            self.assertEqual(first, json.loads(restarted.stdout))


if __name__ == '__main__':
    unittest.main()
