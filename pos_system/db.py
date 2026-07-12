import os
import sys
import sqlite3
from datetime import datetime

DATABASE_URL = os.environ.get('DATABASE_URL', '')
_use_pg = bool(DATABASE_URL)
_param = '%s' if _use_pg else '?'

FIELD_MAP = {
    'Char': ('TEXT', 'VARCHAR'),
    'Text': ('TEXT', 'TEXT'),
    'Integer': ('INTEGER', 'INTEGER'),
    'Float': ('REAL', 'DOUBLE PRECISION'),
    'Boolean': ('INTEGER', 'INTEGER'),
    'Date': ('TEXT', 'DATE'),
    'DateTime': ('TEXT', 'TIMESTAMP'),
    'Many2one': ('INTEGER', 'INTEGER'),
    'Selection': ('TEXT', 'VARCHAR'),
    'One2many': (None, None),
    'Many2many': (None, None),
}


def _get_pg_conn():
    import psycopg2
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    conn.autocommit = True
    return conn


def _get_sqlite_conn():
    from .odoo_orm import DB_PATH
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=OFF")
    return conn


def get_conn():
    if _use_pg:
        return _get_pg_conn()
    return _get_sqlite_conn()


def param_style():
    return _param


def sql_type(field_type_name):
    types = FIELD_MAP.get(field_type_name, ('TEXT', 'TEXT'))
    return types[1] if _use_pg else types[0]


def get_tables(conn):
    if _use_pg:
        cur = conn.cursor()
        cur.execute("SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public'")
        return [row[0] for row in cur.fetchall() if not row[0].endswith('_rel')]
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return [row[0] for row in cur.fetchall() if not row[0].endswith('_rel') and row[0] != 'sqlite_sequence']


def get_table_columns(conn, table):
    if _use_pg:
        cur = conn.cursor()
        cur.execute("SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_name=%s", (table,))
        return {row[0] for row in cur.fetchall()}
    cur = conn.execute('PRAGMA table_info("%s")' % table)
    return {row[1] for row in cur.fetchall()}


def create_table(conn, table, columns):
    if _use_pg:
        cols_sql = ', '.join(columns)
        conn.cursor().execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({cols_sql})')
    else:
        cols_sql = ', '.join(columns)
        conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({cols_sql})')


def create_m2m_table(conn, table, col1, col2):
    if _use_pg:
        conn.cursor().execute(f'CREATE TABLE IF NOT EXISTS "{table}" ("{col1}" INTEGER, "{col2}" INTEGER, PRIMARY KEY ("{col1}", "{col2}"))')
    else:
        conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ("{col1}" INTEGER, "{col2}" INTEGER, PRIMARY KEY ("{col1}", "{col2}"))')


def ensure_bool_column_type(conn, table, name):
    if not _use_pg:
        return
    cur = conn.cursor()
    cur.execute("SELECT data_type FROM information_schema.columns WHERE table_name=%s AND column_name=%s", (table, name))
    row = cur.fetchone()
    if row and row[0].upper() == 'BOOLEAN':
        cur.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{name}" TYPE INTEGER USING (CASE WHEN "{name}" THEN 1 ELSE 0 END)')


def add_column(conn, table, name, col_type):
    try:
        if _use_pg:
            conn.cursor().execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {col_type}')
        else:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {col_type}')
    except Exception:
        pass  # column may already exist


def insert_or_update(conn, table, data, obj_id):
    p = _param
    cols = list(data.keys())
    qcols = [f'"{c}"' for c in cols]
    vals = list(data.values())

    if _use_pg:
        cur = conn.cursor()
        cur.execute(f'SELECT id FROM "{table}" WHERE id={p}', (obj_id,))
        exists = cur.fetchone()
        if exists:
            set_clause = ', '.join([f'{q}={p}' for q in qcols])
            cur.execute(f'UPDATE "{table}" SET {set_clause} WHERE id={p}', vals + [obj_id])
        else:
            all_cols = '"id",' + ','.join(qcols)
            all_ph = p + ',' + ','.join([p for _ in cols])
            cur.execute(f'INSERT INTO "{table}" ({all_cols}) VALUES ({all_ph})', [obj_id] + vals)
    else:
        existing = conn.execute(f'SELECT id FROM "{table}" WHERE id=?', (obj_id,)).fetchone()
        if existing:
            set_clause = ', '.join([f'{q}=?' for q in qcols])
            conn.execute(f'UPDATE "{table}" SET {set_clause} WHERE id=?', vals + [obj_id])
        else:
            all_cols = '"id",' + ','.join(qcols)
            all_ph = '?,' + ','.join(['?' for _ in cols])
            conn.execute(f'INSERT INTO "{table}" ({all_cols}) VALUES ({all_ph})', [obj_id] + vals)


def delete_row(conn, table, obj_id):
    p = _param
    if _use_pg:
        conn.cursor().execute(f'DELETE FROM "{table}" WHERE id={p}', (obj_id,))
    else:
        conn.execute(f'DELETE FROM "{table}" WHERE id=?', (obj_id,))


def load_rows(conn, table, ids, exclude=None):
    cols_str = '*'
    if exclude:
        if _use_pg:
            cur = conn.cursor()
            cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table,))
            all_cols = [r[0] for r in cur.fetchall() if r[0] != exclude]
        else:
            cur = conn.execute(f'PRAGMA table_info("{table}")')
            all_cols = [r[1] for r in cur.fetchall() if r[1] != exclude]
        if all_cols:
            cols_str = ', '.join(f'"{c}"' for c in all_cols)
    if _use_pg:
        cur = conn.cursor()
        params = ','.join(['%s'] * len(ids))
        cur.execute(f'SELECT {cols_str} FROM "{table}" WHERE id IN ({params})', ids)
    else:
        params = ','.join(['?'] * len(ids))
        cur = conn.execute(f'SELECT {cols_str} FROM "{table}" WHERE id IN ({params})', ids)
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def load_table(conn, table, exclude=None):
    cols_str = '*'
    if exclude:
        if _use_pg:
            cur = conn.cursor()
            cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table,))
            all_cols = [r[0] for r in cur.fetchall() if r[0] != exclude]
        else:
            cur = conn.execute(f'PRAGMA table_info("{table}")')
            all_cols = [r[1] for r in cur.fetchall() if r[1] != exclude]
        if all_cols:
            cols_str = ', '.join(f'"{c}"' for c in all_cols)
    if _use_pg:
        cur = conn.cursor()
        cur.execute(f'SELECT {cols_str} FROM "{table}" ORDER BY id')
    else:
        cur = conn.execute(f'SELECT {cols_str} FROM "{table}" ORDER BY id')
    cols = [desc[0] for desc in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def insert_m2m(conn, rel, col1, col2, obj_id, target_ids):
    p = _param
    if _use_pg:
        cur = conn.cursor()
        cur.execute(f'DELETE FROM "{rel}" WHERE "{col1}"={p}', (obj_id,))
        for tid in target_ids:
            cur.execute(f'INSERT INTO "{rel}" ("{col1}", "{col2}") VALUES ({p},{p}) ON CONFLICT DO NOTHING', (obj_id, int(tid)))
    else:
        conn.execute(f'DELETE FROM "{rel}" WHERE "{col1}"=?', (obj_id,))
        for tid in target_ids:
            conn.execute(f'INSERT OR IGNORE INTO "{rel}" ("{col1}", "{col2}") VALUES (?,?)', (obj_id, int(tid)))


def load_m2m(conn, rel, col1, col2, obj_id):
    p = _param
    if _use_pg:
        cur = conn.cursor()
        cur.execute(f'SELECT "{col2}" FROM "{rel}" WHERE "{col1}"={p}', (obj_id,))
        return [row[0] for row in cur.fetchall()]
    cur = conn.execute(f'SELECT "{col2}" FROM "{rel}" WHERE "{col1}"=?', (obj_id,))
    return [row[0] for row in cur.fetchall()]


def commit(conn):
    if not _use_pg:
        conn.commit()
