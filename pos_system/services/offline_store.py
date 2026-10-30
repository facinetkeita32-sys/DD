"""Private sync metadata in the business DB, outside the ORM/backup registry.

No existing table is migrated. These tables are created only after explicit
server enablement or inside a dedicated desktop database.
"""
import json
import os
import uuid

from .. import db

TABLES = {'meta', 'devices', 'grants', 'applied', 'outbox'}


def local_mode():
    return os.environ.get('POS_OFFLINE_MODE') == '1'


def enabled():
    return local_mode() or os.environ.get('OFFLINE_SYNC_ENABLED') == '1'


def query(sql, values=()):
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        try:
            cur.execute(sql, values)
            rows = cur.fetchall() if cur.description else []
            db.commit(conn)
            return rows
        finally:
            cur.close()
    finally:
        conn.close()


def table(kind):
    if kind not in TABLES:
        raise ValueError('Unknown metadata table')
    return '"_offline_' + kind + '"'


def get(kind, key, default=None):
    rows = query(f'SELECT body FROM {table(kind)} WHERE id={db.param_style()}', (key,))
    return json.loads(rows[0][0]) if rows else default


def put(kind, key, value):
    p = db.param_style()
    query(f'INSERT INTO {table(kind)} (id, body) VALUES ({p},{p}) '
          'ON CONFLICT (id) DO UPDATE SET body=excluded.body',
          (key, json.dumps(value, ensure_ascii=False, sort_keys=True)))


def all_rows(kind):
    return [(key, json.loads(body)) for key, body in query(f'SELECT id,body FROM {table(kind)} ORDER BY id')]


def initialize():
    if not enabled():
        return
    conn = db.get_conn()
    try:
        for kind in TABLES:
            cur = conn.cursor()
            cur.execute(f'CREATE TABLE IF NOT EXISTS {table(kind)} (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            cur.close()
        db.commit(conn)
    finally:
        conn.close()
    if not local_mode() and get('meta', 'identity') is None:
        put('meta', 'identity', {'server_id': str(uuid.uuid4()), 'epoch': str(uuid.uuid4())})


def restored_database(conn):
    if enabled() and not local_mode():
        cur = conn.cursor()
        try:
            cur.execute(f'SELECT body FROM {table("meta")} WHERE id={db.param_style()}', ('identity',))
            row = cur.fetchone()
            if row:
                identity = json.loads(row[0])
                identity['epoch'] = str(uuid.uuid4())
                cur.execute(f'UPDATE {table("meta")} SET body={db.param_style()} WHERE id={db.param_style()}',
                            (json.dumps(identity), 'identity'))
        finally:
            cur.close()
