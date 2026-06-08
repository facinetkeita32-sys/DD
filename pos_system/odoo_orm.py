import json
import os
import psycopg2
from psycopg2 import pool, sql
import threading
from datetime import datetime
from collections import OrderedDict
from flask import g

_db_cache = {}
_db_lock = threading.Lock()

DB_HOST = os.environ.get('PGHOST', 'localhost')
DB_PORT = int(os.environ.get('PGPORT', 5432))
DB_NAME = os.environ.get('PGDATABASE', 'pos_db')
DB_USER = os.environ.get('PGUSER', 'pos_user')
DB_PASS = os.environ.get('PGPASSWORD', 'pos_pass')

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
        )
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


HEAVY_COLS = {'logo'}

def _load_cache():
    global _db_cache
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        tables = [row[0] for row in cur.fetchall() if not row[0].endswith('_rel') and row[0] != 'sqlite_sequence']
        cur.close()
        seen = set()
        for table in tables:
            seen.add(table)
            _db_cache.setdefault(table, {'_seq': 0, '_data': OrderedDict()})
            tbl = _db_cache[table]
            tbl['_seq'] = 0
            tbl['_data'].clear()
            cur = conn.cursor()
            cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name=%s ORDER BY ordinal_position", (table,))
            all_cols = [row[0] for row in cur.fetchall()]
            cur.close()
            light_cols = [c for c in all_cols if c not in HEAVY_COLS]
            col_list = ','.join('"{}"'.format(c) for c in light_cols)
            cur = conn.cursor()
            cur.execute('SELECT {} FROM "{}" ORDER BY id'.format(col_list, table))
            for row in cur.fetchall():
                data = dict(zip(light_cols, row))
                rid = data.pop('id')
                tbl['_data'][rid] = data
                if rid > tbl['_seq']:
                    tbl['_seq'] = rid
            cur.close()
        for table in list(_db_cache.keys()):
            if table not in seen and table != 'sqlite_sequence':
                del _db_cache[table]
    finally:
        put_conn(conn)


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
        raise
    finally:
        put_conn(conn)


def _persist_delete(cls, obj_id):
    table = cls._name
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM "{}" WHERE id=%s'.format(table), (obj_id,))
        cur.close()
        conn.commit()
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
            return float(value)
        return value


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
            _ensure_table(new_class)
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

    def write(self, vals):
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for fname, value in vals.items():
            if fname in self._fields and not self._fields[fname].readonly:
                field = self._fields[fname]
                self._data[fname] = field.convert(value)
        self._data['write_date'] = now
        self._data['write_uid'] = self._get_user_id()
        self._save()
        return True

    def _save(self):
        tbl = _db_cache[self._name]
        tbl['_data'][self.id] = dict(self._data)
        _persist_write(self.__class__, self.id)

    def unlink(self):
        tbl = _db_cache[self._name]
        if self.id in tbl['_data']:
            del tbl['_data'][self.id]
        _persist_delete(self.__class__, self.id)
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
        tbl['_data'][new_id] = data
        _persist_write(cls, new_id)
        obj = cls(**data)
        obj.id = new_id
        return obj

    @classmethod
    def search(cls, domain=None, order=None, limit=None, offset=0):
        domain = domain or []
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
        tbl = _db_cache.get(cls._name, {'_data': OrderedDict()})
        results = []
        for rid in ids:
            if rid in tbl['_data']:
                obj = cls(**tbl['_data'][rid])
                obj.id = rid
                results.append(obj)
        return results

    @classmethod
    def search_count(cls, domain=None):
        return len(cls.search(domain))

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
