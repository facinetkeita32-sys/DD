import json
import os
import re
import time
import psycopg2
from psycopg2 import pool, sql
import threading
from datetime import datetime
from collections import OrderedDict
from flask import g

_db_cache = {}
_db_lock = threading.Lock()
_cache_loaded = False
_cache_loaded_at = 0.0
_all_model_classes = []
_CACHE_VERSION_FILE = '/tmp/_pos_cache_version'
_tables_ensured = False


def _parse_db_url(url):
    m = re.match(r'postgres(?:ql)?://(?:([^:]+)(?::([^@]*))?@)?([^:]+)(?::(\d+))?/([^?]+)', url)
    if m:
        return {
            'user': m.group(1) or 'postgres',
            'password': m.group(2) or '',
            'host': m.group(3) or 'localhost',
            'port': int(m.group(4)) if m.group(4) else 5432,
            'dbname': m.group(5) or 'postgres',
        }
    return None


_db_url = os.environ.get('DATABASE_URL', '')
_db_parsed = _parse_db_url(_db_url) if _db_url else None

DB_HOST = os.environ.get('PGHOST', _db_parsed['host'] if _db_parsed else 'localhost')
DB_PORT = int(os.environ.get('PGPORT', _db_parsed['port'] if _db_parsed else 5432))
DB_NAME = os.environ.get('PGDATABASE', _db_parsed['dbname'] if _db_parsed else 'pos_db')
DB_USER = os.environ.get('PGUSER', _db_parsed['user'] if _db_parsed else 'pos_user')
DB_PASS = os.environ.get('PGPASSWORD', _db_parsed['password'] if _db_parsed else 'pos_pass')

_pool = None
_pool_pid = None


def get_pool():
    global _pool, _pool_pid
    pid = os.getpid()
    if _pool is not None and _pool_pid != pid:
        try:
            _pool.closeall()
        except Exception:
            pass
        _pool = None
    if _pool is None:
        _pool_pid = pid
        last_error = None
        delays = [1, 2, 4, 8, 15]
        for attempt in range(1 + len(delays)):
            try:
                _pool = pool.ThreadedConnectionPool(
                    minconn=1,
                    maxconn=5,
                    host=DB_HOST,
                    port=DB_PORT,
                    dbname=DB_NAME,
                    user=DB_USER,
                    password=DB_PASS,
                )
                break
            except Exception as e:
                last_error = e
                if attempt < len(delays):
                    print('DB connection attempt {}/{} failed: {}'.format(attempt + 1, 1 + len(delays), e))
                    time.sleep(delays[attempt])
                else:
                    print('DB connection failed after {} attempts: {}'.format(1 + len(delays), e))
        if _pool is None:
            raise last_error
    return _pool


def get_conn():
    try:
        if '_db_conn' in g:
            return g._db_conn
    except Exception:
        pass
    conn = get_pool().getconn()
    try:
        g._db_conn = conn
    except Exception:
        pass
    return conn


def put_conn(conn):
    try:
        if getattr(g, '_db_conn', None) is conn:
            return
    except Exception:
        pass
    try:
        get_pool().putconn(conn)
    except Exception:
        pass


FIELD_TO_SQLITE = {
    'Char': 'TEXT',
    'Text': 'TEXT',
    'Integer': 'INTEGER',
    'Float': 'REAL',
    'Boolean': 'INTEGER',
    'Date': 'TEXT',
    'DateTime': 'TEXT',
    'Many2one': 'INTEGER',
    'Selection': 'TEXT',
    'One2many': None,
    'Many2many': None,
}


def _sql_type(field):
    tname = type(field).__name__
    return FIELD_TO_SQLITE.get(tname, 'TEXT')


def _ensure_table(model_class):
    conn = get_conn()
    try:
        table = model_class._name
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM information_schema.tables WHERE table_name=%s", (table,))
        exists = cur.fetchone()
        cur.close()
        if exists:
            _migrate_table(conn, model_class)
            return

        cols = ['id INTEGER PRIMARY KEY']
        for fname, field in model_class._fields.items():
            if fname == 'id':
                continue
            st = _sql_type(field)
            if st is None:
                continue
            cols.append('"{}" {}'.format(fname, st))
        cols.append('"create_date" TEXT')
        cols.append('"write_date" TEXT')
        cols.append('"create_uid" INTEGER')
        cols.append('"write_uid" INTEGER')

        cur = conn.cursor()
        try:
            cur.execute('CREATE TABLE IF NOT EXISTS "{}" ({})'.format(table, ', '.join(cols)))
            conn.commit()
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            _migrate_table(conn, model_class)
        finally:
            cur.close()

        for fname, field in model_class._fields.items():
            if isinstance(field, Many2many):
                rel = field.rel or '{}_{}_rel'.format(table, field.comodel_name)
                col1 = field.column1 or '{}_id'.format(table)
                col2 = field.column2 or '{}_id'.format(field.comodel_name)
                cur = conn.cursor()
                try:
                    cur.execute('CREATE TABLE IF NOT EXISTS "{}" ("{}" INTEGER, "{}" INTEGER, PRIMARY KEY ("{}", "{}"))'.format(rel, col1, col2, col1, col2))
                    conn.commit()
                except psycopg2.errors.UniqueViolation:
                    conn.rollback()
                finally:
                    cur.close()
    finally:
        put_conn(conn)


def _migrate_table(conn, model_class):
    table = model_class._name
    cur = conn.cursor()
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s", (table,))
    existing = {row[0] for row in cur.fetchall()}
    cur.close()
    for fname, field in model_class._fields.items():
        if fname == 'id' or fname in existing:
            continue
        st = _sql_type(field)
        if st is None:
            continue
        cur = conn.cursor()
        cur.execute('ALTER TABLE "{}" ADD COLUMN "{}" {}'.format(table, fname, st))
        cur.close()
        conn.commit()


HEAVY_COLS = {'logo', 'image'}
DB_ONLY_TABLES = {'pos.order', 'pos.order.line', 'pos.payment', 'pos.session', 'login.log', 'inventory.item'}


def _ensure_all_tables():
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        existing = {row[0] for row in cur.fetchall()}
        cur.close()
        for cls in _all_model_classes:
            if cls._name in existing:
                try:
                    _migrate_table(conn, cls)
                except Exception:
                    import traceback
                    print('Error migrating table {}:'.format(cls._name))
                    traceback.print_exc()
            else:
                try:
                    _ensure_table(cls)
                except Exception:
                    import traceback
                    print('Error ensuring table {}:'.format(cls._name))
                    traceback.print_exc()
    finally:
        put_conn(conn)


def _get_model_columns(model_cls):
    """Build column list from model field definitions (no DB query needed)."""
    cols = ['id']
    for fname, field in model_cls._fields.items():
        if fname == 'id':
            continue
        if isinstance(field, (One2many, Many2many)):
            continue
        cols.append(fname)
    cols += ['create_date', 'write_date', 'create_uid', 'write_uid']
    return cols


def _read_cache_version():
    try:
        with open(_CACHE_VERSION_FILE, 'r') as f:
            return float(f.read().strip())
    except Exception:
        return 0.0

def _write_cache_version():
    try:
        with open(_CACHE_VERSION_FILE, 'w') as f:
            f.write(str(time.time()))
    except Exception:
        pass

def _load_cache():
    global _db_cache, _cache_loaded, _cache_loaded_at
    if _cache_loaded:
        if _read_cache_version() <= _cache_loaded_at:
            return
    with _db_lock:
        if _cache_loaded:
            if _read_cache_version() <= _cache_loaded_at:
                return
        if not _tables_ensured:
            try:
                _ensure_all_tables()
                _tables_ensured = True
            except Exception:
                print('WARN: _ensure_all_tables() failed, continuing', flush=True)
                import traceback
                traceback.print_exc()
        conn = get_conn()
        try:
            now = time.time()
            loaded_any = False
            for cls in _all_model_classes:
                table = cls._name
                if table in DB_ONLY_TABLES or table.endswith('_rel'):
                    continue
                _db_cache.setdefault(table, {'_seq': 0, '_data': OrderedDict()})
                new_data = OrderedDict()
                new_seq = 0
                try:
                    all_cols = _get_model_columns(cls)
                    light_cols = [c for c in all_cols if c not in HEAVY_COLS]
                    if light_cols:
                        col_list = ','.join('"{}"'.format(c) for c in light_cols)
                        cur = conn.cursor()
                        cur.execute('SELECT {} FROM "{}" ORDER BY id'.format(col_list, table))
                        for row in cur:
                            data = dict(zip(light_cols, row))
                            rid = data.pop('id')
                            new_data[rid] = data
                            if rid > new_seq:
                                new_seq = rid
                        cur.close()
                    tbl = _db_cache[table]
                    tbl['_seq'] = new_seq
                    tbl['_data'] = new_data
                    if new_data:
                        loaded_any = True
                except Exception:
                    print('WARN: could not load table "{}", skipping'.format(table), flush=True)
                    import traceback
                    traceback.print_exc()
            elapsed = time.time() - now
            print('DB cache loaded {} tables in {:.2f}s'.format(len(_db_cache), elapsed), flush=True)
            if loaded_any:
                _cache_loaded = True
                _cache_loaded_at = time.time()
        finally:
            try:
                put_conn(conn)
            except Exception:
                pass


def _load_heavy(cls, obj_id, col_name):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('SELECT "{}" FROM "{}" WHERE id=%s'.format(col_name, cls._name), (obj_id,))
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    finally:
        put_conn(conn)


def _batch_load_heavy(cls, ids, col_name):
    if not ids:
        return {}
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('SELECT id, "{}" FROM "{}" WHERE id = ANY(%s)'.format(col_name, cls._name), (list(ids),))
        result = dict(cur.fetchall())
        cur.close()
        return result
    finally:
        put_conn(conn)


def _persist_write(cls, obj_id):
    table = cls._name
    data = dict(_db_cache[table]['_data'][obj_id])
    conn = get_conn()
    try:
        cols = []
        vals = []
        for k, v in data.items():
            if k == 'id':
                continue
            if k in HEAVY_COLS:
                continue
            field = cls._fields.get(k)
            if field and isinstance(field, (One2many, Many2many)):
                continue
            if isinstance(v, bool):
                v = 1 if v else 0
            cols.append(k)
            vals.append(v)
        if not cols:
            return
        qcols = ['"{}"'.format(c) for c in cols]
        all_cols = '"id",' + ','.join(qcols)
        all_ph = '%s,' + ','.join(['%s' for _ in cols])
        update_set = ', '.join(['{}=EXCLUDED.{}'.format(q, q) for q in qcols])
        sql = 'INSERT INTO "{}" ({}) VALUES ({}) ON CONFLICT (id) DO UPDATE SET {}'.format(
            table, all_cols, all_ph, update_set)
        cur = conn.cursor()
        cur.execute(sql, [obj_id] + vals)
        cur.close()
        conn.commit()
    except Exception as e:
        import traceback
        print('SQL ERROR ({}): {}'.format(table, e))
        traceback.print_exc()
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        put_conn(conn)


def _persist_write_data(cls, obj_id, data):
    table = cls._name
    conn = get_conn()
    try:
        cols = []
        vals = []
        for k, v in data.items():
            if k == 'id':
                continue
            if k in HEAVY_COLS:
                continue
            field = cls._fields.get(k)
            if field and isinstance(field, (One2many, Many2many)):
                continue
            if isinstance(v, bool):
                v = 1 if v else 0
            cols.append(k)
            vals.append(v)
        if not cols:
            return
        qcols = ['"{}"'.format(c) for c in cols]
        all_cols = '"id",' + ','.join(qcols)
        all_ph = '%s,' + ','.join(['%s' for _ in cols])
        update_set = ', '.join(['{}=EXCLUDED.{}'.format(q, q) for q in qcols])
        sql_cmd = 'INSERT INTO "{}" ({}) VALUES ({}) ON CONFLICT (id) DO UPDATE SET {}'.format(
            table, all_cols, all_ph, update_set)
        cur = conn.cursor()
        cur.execute(sql_cmd, [obj_id] + vals)
        cur.close()
        conn.commit()
    except Exception as e:
        import traceback
        print('SQL ERROR ({}): {}'.format(table, e))
        traceback.print_exc()
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        put_conn(conn)


def _persist_delete(cls, obj_id):
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM "{}" WHERE id=%s'.format(cls._name), (obj_id,))
        cur.close()
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        put_conn(conn)


def _persist_bulk_delete(cls, ids):
    if not ids:
        return
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM "{}" WHERE id = ANY(%s)'.format(cls._name), (list(ids),))
        cur.close()
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        put_conn(conn)


def _persist_heavy_column(cls, obj_id, col_name, value):
    conn = get_conn()
    try:
        cur = conn.cursor()
        if isinstance(value, bool):
            value = 1 if value else 0
        cur.execute('UPDATE "{}" SET "{}"=%s WHERE id=%s'.format(cls._name, col_name), (value, obj_id))
        cur.close()
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        put_conn(conn)


def _persist_m2m(cls, obj_id, field_name, target_ids):
    field = cls._fields[field_name]
    rel = field.rel or '{}_{}_rel'.format(cls._name, field.comodel_name)
    col1 = field.column1 or '{}_id'.format(cls._name)
    col2 = field.column2 or '{}_id'.format(field.comodel_name)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM "{}" WHERE "{}"=%s'.format(rel, col1), (obj_id,))
        for tid in target_ids:
            cur.execute('INSERT INTO "{}" ("{}", "{}") VALUES (%s,%s) ON CONFLICT DO NOTHING'.format(rel, col1, col2), (obj_id, int(tid)))
        cur.close()
        conn.commit()
    finally:
        put_conn(conn)


def _load_m2m(cls, obj_id, field_name):
    field = cls._fields[field_name]
    rel = field.rel or '{}_{}_rel'.format(cls._name, field.comodel_name)
    col1 = field.column1 or '{}_id'.format(cls._name)
    col2 = field.column2 or '{}_id'.format(field.comodel_name)
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('SELECT "{}" FROM "{}" WHERE "{}"=%s'.format(col2, rel, col1), (obj_id,))
        result = [row[0] for row in cur.fetchall()]
        cur.close()
        return result
    finally:
        put_conn(conn)



class Field:
    def __init__(self, string=None, default=None, required=False, readonly=False, help=None):
        self.string = string
        self.default = default
        self.required = required
        self.readonly = readonly
        self.help = help

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        import sys
        _mod = sys.modules[__name__]
        _env = _mod.env
        val = obj._data.get(self.name, self._get_default())
        if isinstance(self, Many2one) and val:
            records = _env[self.comodel_name].browse(val)
            return records[0] if records else False
        if isinstance(self, One2many):
            return _env[self.comodel_name].search([(self.inverse_field, '=', obj.id)])
        if isinstance(self, Many2many):
            return obj._get_m2m(self.name)
        return val

    def __set__(self, obj, value):
        obj._data[self.name] = self.convert(value)

    def _get_default(self):
        d = self.default() if callable(self.default) else self.default
        return d

    def convert(self, value):
        return value


class Boolean(Field):
    def convert(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        return False


class Integer(Field):
    def convert(self, value):
        return int(value) if value is not None else value


class Float(Field):
    def __init__(self, digits=None, **kwargs):
        super().__init__(**kwargs)
        self.digits = digits

    def convert(self, value):
        if value is not None:
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0.0
        return 0.0


class Char(Field):
    def __init__(self, size=None, **kwargs):
        super().__init__(**kwargs)
        self.size = size

    def convert(self, value):
        if value is not None:
            return str(value)[:self.size] if self.size else str(value)
        return value


class Text(Field):
    def convert(self, value):
        return str(value) if value is not None else value


class Date(Field):
    def convert(self, value):
        if isinstance(value, str):
            return value
        return value.strftime('%Y-%m-%d') if value else None


class DateTime(Field):
    def convert(self, value):
        if isinstance(value, str):
            return value
        return value.strftime('%Y-%m-%d %H:%M:%S') if value else None


class Many2one(Field):
    def __init__(self, comodel_name, **kwargs):
        super().__init__(**kwargs)
        self.comodel_name = comodel_name

    def convert(self, value):
        if value is None or value == 0:
            return False
        return int(value)


class One2many(Field):
    def __init__(self, comodel_name, inverse_field, **kwargs):
        super().__init__(**kwargs)
        self.comodel_name = comodel_name
        self.inverse_field = inverse_field


class Many2many(Field):
    def __init__(self, comodel_name, rel=None, column1=None, column2=None, **kwargs):
        super().__init__(**kwargs)
        self.comodel_name = comodel_name
        self.rel = rel
        self.column1 = column1
        self.column2 = column2


class Selection(Field):
    def __init__(self, selection, **kwargs):
        super().__init__(**kwargs)
        self.selection = selection

    def convert(self, value):
        return str(value) if value else value


class BaseModel(type):
    def __new__(cls, name, bases, attrs):
        new_class = super().__new__(cls, name, bases, attrs)
        if name != 'Model':
            fields = {}
            for attr_name, attr_value in attrs.items():
                if isinstance(attr_value, Field):
                    fields[attr_name] = attr_value
            new_class._fields = fields
            model_name = getattr(new_class, '_name', name.lower())
            new_class._name = model_name
            _db_cache.setdefault(model_name, {'_seq': 0, '_data': OrderedDict()})
            _all_model_classes.append(new_class)
        return new_class


class Model(metaclass=BaseModel):
    _name = None
    _description = None
    _rec_name = 'name'
    _order = 'id'

    id = Integer(string='ID', readonly=True)
    create_date = DateTime(string='Created on', readonly=True)
    write_date = DateTime(string='Last Updated on', readonly=True)
    create_uid = Many2one('res.users', string='Created by', readonly=True)
    write_uid = Many2one('res.users', string='Last Updated by', readonly=True)

    def __init__(self, **kwargs):
        self._data = {}
        for fname, field in self._fields.items():
            if isinstance(field, (One2many, Many2many)):
                continue
            if field.default is not None:
                default = field.default() if callable(field.default) else field.default
                self._data[fname] = field.convert(default) if default is not None else field.convert(None)
            else:
                if isinstance(field, (Many2one, Boolean)):
                    self._data[fname] = False
                elif isinstance(field, Float):
                    self._data[fname] = 0.0
                elif isinstance(field, Integer):
                    self._data[fname] = 0
                elif isinstance(field, (Char, Text, Selection)):
                    self._data[fname] = ''
                else:
                    self._data[fname] = None
        for k, v in kwargs.items():
            if k in self._fields and not isinstance(self._fields[k], (One2many, Many2many)):
                self._data[k] = self._fields[k].convert(v)

    def __setattr__(self, name, value):
        if '_fields' in self.__class__.__dict__ and name in self._fields:
            field = self._fields[name]
            if isinstance(field, Many2one) and hasattr(value, 'id'):
                value = value.id
            self._data[name] = field.convert(value)
        else:
            super().__setattr__(name, value)

    def _get_m2m(self, name):
        field = self._fields[name]
        col2 = field.column2 or '{}_id'.format(field.comodel_name)
        ids = _load_m2m(self.__class__, self.id, name)
        return self.env[field.comodel_name].browse(ids)

    @classmethod
    def _get_user_id(cls):
        try:
            return getattr(g, 'user_id', False)
        except Exception:
            return False

    @classmethod
    def bulk_write(cls, ids, field, value):
        if cls._name in DB_ONLY_TABLES or not ids:
            return
        conn = get_conn()
        try:
            sql_cmd = 'UPDATE "{}" SET "{}" = %s WHERE id = ANY(%s)'.format(cls._name, field)
            cur = conn.cursor()
            cur.execute(sql_cmd, (value, list(ids)))
            cur.close()
            conn.commit()
        except Exception as e:
            import traceback
            print('SQL ERROR (bulk): {}'.format(e))
            traceback.print_exc()
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            put_conn(conn)
        if cls._name in _db_cache:
            for pid in ids:
                if pid in _db_cache[cls._name]['_data']:
                    _db_cache[cls._name]['_data'][pid][field] = value
        _write_cache_version()

    def write(self, vals):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for fname, value in vals.items():
            if fname in self._fields and not self._fields[fname].readonly:
                field = self._fields[fname]
                self._data[fname] = field.convert(value)
        self._data['write_date'] = now
        self._data['write_uid'] = self._get_user_id()
        for fname in vals:
            if fname in HEAVY_COLS and fname in self._fields:
                _persist_heavy_column(self.__class__, self.id, fname, self._data.get(fname))
        self._save()
        return True

    def _save(self):
        if self._name in DB_ONLY_TABLES:
            data = dict(self._data)
            for k in list(data):
                if k in HEAVY_COLS:
                    del data[k]
            _persist_write_data(self.__class__, self.id, data)
            return
        tbl = _db_cache[self._name]
        data = dict(self._data)
        for k in list(data):
            if k in HEAVY_COLS:
                del data[k]
        tbl['_data'][self.id] = data
        _persist_write(self.__class__, self.id)
        _write_cache_version()

    def unlink(self):
        if self._name in DB_ONLY_TABLES:
            _persist_delete(self.__class__, self.id)
            return True
        tbl = _db_cache[self._name]
        if self.id in tbl['_data']:
            del tbl['_data'][self.id]
        _persist_delete(self.__class__, self.id)
        _write_cache_version()
        return True

    def read(self, fields=None):
        result = {'id': self.id}
        fnames = fields if fields else list(self._fields.keys())
        for fname in fnames:
            if fname in self._fields:
                val = self._data.get(fname)
                if isinstance(self._fields[fname], Many2one) and val:
                    comodel = self._fields[fname].comodel_name
                    if comodel in _db_cache:
                        name = _db_cache[comodel]['_data'].get(val, {}).get(self._rec_name, '')
                        result[fname] = [val, str(name)]
                    else:
                        result[fname] = val
                else:
                    result[fname] = val
        return result

    def name_get(self):
        name = self._data.get(self._rec_name, '[{} {}]'.format(self._name, self.id))
        return (self.id, str(name))

    @classmethod
    def create(cls, vals):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        if cls._name in DB_ONLY_TABLES:
            return cls._db_create(vals)
        tbl = _db_cache[cls._name]
        tbl['_seq'] += 1
        new_id = tbl['_seq']
        data = {'id': new_id}
        for fname, field in cls._fields.items():
            if fname == 'id':
                continue
            if fname in vals:
                data[fname] = field.convert(vals[fname])
            elif field.default is not None:
                default = field.default() if callable(field.default) else field.default
                data[fname] = field.convert(default) if default is not None else field.convert(None)
            else:
                data[fname] = field.convert(None)
        data['create_date'] = now
        data['write_date'] = now
        uid = cls._get_user_id()
        data['create_uid'] = uid
        data['write_uid'] = uid
        cache_data = {k: v for k, v in data.items() if k not in HEAVY_COLS}
        tbl['_data'][new_id] = cache_data
        _persist_write(cls, new_id)
        _write_cache_version()
        for fname in data:
            if fname in HEAVY_COLS and data.get(fname) is not None:
                _persist_heavy_column(cls, new_id, fname, data[fname])
        obj = cls(**data)
        obj.id = new_id
        return obj

    @classmethod
    def search(cls, domain=None, order=None, limit=None, offset=0):
        domain = domain or []
        if cls._name in DB_ONLY_TABLES:
            return cls._db_search(domain, order, limit, offset)
        tbl = _db_cache.get(cls._name, {'_data': OrderedDict()})
        results = []
        for rid, rdata in tbl['_data'].items():
            if cls._match_domain(rdata, domain):
                obj = cls(**rdata)
                obj.id = rid
                results.append(obj)
        order = order or cls._order
        if order:
            reverse = False
            order_field = order
            if order.startswith('-'):
                reverse = True
                order_field = order[1:]
            parts = order_field.rsplit(None, 1)
            if len(parts) == 2 and parts[1].lower() == 'desc':
                reverse = True
                order_field = parts[0]
            results.sort(key=lambda x: x._data.get(order_field, ''), reverse=reverse)
        if offset:
            results = results[offset:]
        if limit:
            results = results[:limit]
        return results

    @classmethod
    def browse(cls, ids):
        if isinstance(ids, int):
            ids = [ids]
        if cls._name in DB_ONLY_TABLES:
            return cls._db_browse(ids)
        tbl = _db_cache.get(cls._name, {'_data': OrderedDict()})
        results = []
        for rid in ids:
            if rid in tbl['_data']:
                obj = cls(**tbl['_data'][rid])
                obj.id = rid
                results.append(obj)
        return results

    @classmethod
    def _db_create(cls, vals):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn = get_conn()
        try:
            cur = conn.cursor()
            with _db_lock:
                cur.execute('SELECT COALESCE(MAX(id), 0) + 1 FROM "{}" FOR UPDATE'.format(cls._name))
                new_id = cur.fetchone()[0]
            cur.close()
            data = {'id': new_id}
            for fname, field in cls._fields.items():
                if fname == 'id':
                    continue
                if fname in vals:
                    data[fname] = field.convert(vals[fname])
                elif field.default is not None:
                    default = field.default() if callable(field.default) else field.default
                    data[fname] = field.convert(default) if default is not None else field.convert(None)
                else:
                    data[fname] = field.convert(None)
            data['create_date'] = now
            data['write_date'] = now
            uid = cls._get_user_id()
            data['create_uid'] = uid
            data['write_uid'] = uid
            persist_data = {k: v for k, v in data.items() if k not in HEAVY_COLS}
            _persist_write_data(cls, new_id, persist_data)
            for fname in data:
                if fname in HEAVY_COLS and data.get(fname) is not None:
                    _persist_heavy_column(cls, new_id, fname, data[fname])
            obj = cls(**data)
            obj.id = new_id
            return obj
        finally:
            put_conn(conn)

    @classmethod
    def _db_search_count(cls, domain=None):
        domain = domain or []
        conn = get_conn()
        try:
            where_clause, params = cls._domain_to_sql(domain)
            sql_cmd = 'SELECT COUNT(*) FROM "{}" {}'.format(cls._name, where_clause)
            cur = conn.cursor()
            cur.execute(sql_cmd, params)
            count = cur.fetchone()[0]
            cur.close()
            return count
        finally:
            put_conn(conn)

    @classmethod
    def _db_search(cls, domain=None, order=None, limit=None, offset=0):
        domain = domain or []
        conn = get_conn()
        try:
            all_cols = _get_model_columns(cls)
            light_cols = [c for c in all_cols if c not in HEAVY_COLS]
            if not light_cols:
                return []
            where_clause, params = cls._domain_to_sql(domain)
            order_clause = ''
            order = order or cls._order
            if order:
                reverse = False
                order_field = order
                if order.startswith('-'):
                    reverse = True
                    order_field = order[1:]
                parts = order_field.rsplit(None, 1)
                if len(parts) == 2 and parts[1].lower() == 'desc':
                    reverse = True
                    order_field = parts[0]
                order_clause = 'ORDER BY "{}" {}'.format(order_field, 'DESC' if reverse else 'ASC')
            limit_clause = ''
            if limit:
                limit_clause = 'LIMIT {}'.format(limit)
            offset_clause = ''
            if offset:
                offset_clause = 'OFFSET {}'.format(offset)
            col_list = ','.join('"{}"'.format(c) for c in light_cols)
            sql_cmd = 'SELECT {} FROM "{}" {} {} {} {}'.format(col_list, cls._name, where_clause, order_clause, limit_clause, offset_clause)
            cur = conn.cursor()
            cur.execute(sql_cmd, params)
            results = []
            for row in cur:
                data = dict(zip(light_cols, row))
                rid = data.pop('id')
                obj = cls(**data)
                obj.id = rid
                results.append(obj)
            cur.close()
            return results
        finally:
            put_conn(conn)

    @classmethod
    def _db_browse(cls, ids):
        if not ids:
            return []
        conn = get_conn()
        try:
            all_cols = _get_model_columns(cls)
            light_cols = [c for c in all_cols if c not in HEAVY_COLS]
            if not light_cols:
                return []
            col_list = ','.join('"{}"'.format(c) for c in light_cols)
            cur = conn.cursor()
            cur.execute('SELECT {} FROM "{}" WHERE id = ANY(%s)'.format(col_list, cls._name), (list(ids),))
            results = []
            for row in cur:
                data = dict(zip(light_cols, row))
                rid = data.pop('id')
                obj = cls(**data)
                obj.id = rid
                results.append(obj)
            cur.close()
            return results
        finally:
            put_conn(conn)

    @classmethod
    def _domain_to_sql(cls, domain):
        if not domain:
            return '', []
        conditions = []
        params = []
        i = 0
        while i < len(domain):
            item = domain[i]
            if item == '!':
                cond, p = cls._domain_to_sql([domain[i + 1]])
                i += 2
                if cond:
                    conditions.append('(NOT ({})'.format(cond[3:]) if cond.startswith('AND ') else '(NOT {})'.format(cond))
                    params.extend(p)
                continue
            elif item == '|':
                left_cond, left_p = cls._domain_to_sql([domain[i + 1]])
                right_cond, right_p = cls._domain_to_sql([domain[i + 2]])
                i += 3
                if left_cond and right_cond:
                    conditions.append('({} OR {})'.format(left_cond, right_cond))
                    params.extend(left_p + right_p)
                continue
            elif isinstance(item, (list, tuple)) and len(item) == 3 or item == '&' or (isinstance(item, str) and item not in ('|', '!')):
                and_conds = []
                and_params = []
                if not (isinstance(item, (list, tuple)) and len(item) == 3):
                    i += 1
                while i < len(domain) and isinstance(domain[i], (list, tuple)) and len(domain[i]) == 3:
                    field, operator, value = domain[i]
                    col = '"{}"'.format(field)
                    if operator == '=':
                        and_conds.append('{} = %s'.format(col))
                        and_params.append(value)
                    elif operator == '!=':
                        and_conds.append('{} != %s'.format(col))
                        and_params.append(value)
                    elif operator == '>':
                        and_conds.append('{} > %s'.format(col))
                        and_params.append(value)
                    elif operator == '<':
                        and_conds.append('{} < %s'.format(col))
                        and_params.append(value)
                    elif operator == '>=':
                        and_conds.append('{} >= %s'.format(col))
                        and_params.append(value)
                    elif operator == '<=':
                        and_conds.append('{} <= %s'.format(col))
                        and_params.append(value)
                    elif operator == 'in':
                        if isinstance(value, (list, tuple)):
                            if not value:
                                and_conds.append('1=0')
                            else:
                                placeholders = ','.join(['%s'] * len(value))
                                and_conds.append('{} IN ({})'.format(col, placeholders))
                                and_params.extend(value)
                        else:
                            and_conds.append('{} = %s'.format(col))
                            and_params.append(value)
                    elif operator == 'not in':
                        if isinstance(value, (list, tuple)):
                            if not value:
                                and_conds.append('1=1')
                            else:
                                placeholders = ','.join(['%s'] * len(value))
                                and_conds.append('{} NOT IN ({})'.format(col, placeholders))
                                and_params.extend(value)
                        else:
                            and_conds.append('{} != %s'.format(col))
                            and_params.append(value)
                    elif operator in ('like', 'ilike'):
                        and_conds.append('{} ILIKE %s'.format(col))
                        and_params.append('%{}%'.format(value))
                    i += 1
                if and_conds:
                    conditions.append('({})'.format(' AND '.join(and_conds)))
                    params.extend(and_params)
                continue
            else:
                i += 1
        if conditions:
            return 'WHERE {}'.format(' AND '.join(conditions)), params
        return '', []

    @classmethod
    def search_count(cls, domain=None):
        if cls._name in DB_ONLY_TABLES:
            return cls._db_search_count(domain)
        tbl = _db_cache.get(cls._name)
        if not tbl:
            return 0
        if not domain:
            return len(tbl['_data'])
        count = 0
        for rid, rdata in tbl['_data'].items():
            if cls._match_domain(rdata, domain):
                count += 1
        return count

    @classmethod
    def _match_domain(cls, data, domain):
        if not domain:
            return True

        def _is_condition(item):
            return isinstance(item, (list, tuple)) and len(item) == 3

        stack = []
        i = len(domain) - 1
        while i >= 0:
            item = domain[i]
            if _is_condition(item):
                field, operator, value = item
                actual = data.get(field)
                result = cls._eval_condition(actual, operator, value)
                stack.append(result)
            elif item == '!':
                if stack:
                    stack.append(not stack.pop())
            elif item == '|':
                if len(stack) >= 2:
                    r1 = stack.pop()
                    r2 = stack.pop()
                    stack.append(r1 or r2)
            elif item == '&' or (isinstance(item, str) and item not in ('|', '!')):
                if len(stack) >= 2:
                    r1 = stack.pop()
                    r2 = stack.pop()
                    stack.append(r1 and r2)
            else:
                stack.append(True)
            i -= 1

        if not stack:
            return True
        return all(stack)

    @classmethod
    def _eval_condition(cls, actual, operator, value):
        if operator == '=':
            return actual == value
        elif operator == '!=':
            return actual != value
        elif operator == '>':
            return actual is not None and actual > value
        elif operator == '<':
            return actual is not None and actual < value
        elif operator == '>=':
            return actual is not None and actual >= value
        elif operator == '<=':
            return actual is not None and actual <= value
        elif operator == 'in':
            return actual in value if isinstance(value, (list, tuple)) else actual == value
        elif operator == 'not in':
            return actual not in value if isinstance(value, (list, tuple)) else actual != value
        elif operator == 'like':
            return value.lower() in str(actual).lower()
        elif operator == 'ilike':
            return value.lower() in str(actual).lower()
        elif operator == 'child_of':
            return cls._check_child_of(data, field, value)
        return True

    @classmethod
    def _check_child_of(cls, data, field, value):
        parent_field = '{}_id'.format(field)
        current = data.get(parent_field)
        visited = set()
        while current:
            if current == value:
                return True
            if current in visited:
                break
            visited.add(current)
            parent_data = _db_cache.get(cls._name, {}).get('_data', {}).get(current, {})
            current = parent_data.get(parent_field)
        return False

    @classmethod
    def _get_table(cls):
        return _db_cache.setdefault(cls._name, {'_seq': 0, '_data': OrderedDict()})

    def _get_data_dict(self):
        return self._data

    @classmethod
    def get_all(cls):
        tbl = _db_cache.get(cls._name, {'_data': OrderedDict()})
        results = []
        for rid in sorted(tbl['_data'].keys()):
            obj = cls(**tbl['_data'][rid])
            obj.id = rid
            results.append(obj)
        return results

    @classmethod
    def clear(cls):
        if cls._name in _db_cache:
            _db_cache[cls._name] = {'_seq': 0, '_data': OrderedDict()}
        conn = get_conn()
        try:
            cur = conn.cursor()
            cur.execute('DELETE FROM "{}"'.format(cls._name))
            cur.close()
            conn.commit()
        finally:
            put_conn(conn)


class Environment:
    def __init__(self):
        self._models = {}

    def __getitem__(self, model_name):
        if model_name not in self._models:
            for klass in Model.__subclasses__():
                if klass._name == model_name:
                    self._models[model_name] = klass
                    break
        return self._models.get(model_name)


env = Environment()
