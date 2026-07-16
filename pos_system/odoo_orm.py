import json
import os
import sys
import threading
from datetime import datetime
from collections import OrderedDict
from flask import g

from . import db
from . import redis_cache

_db_cache = {}
_db_lock = threading.Lock()

def _get_db_path():
    env_db = os.environ.get('DB_PATH') or os.environ.get('RENDER_DISK_PATH')
    if env_db:
        p = os.path.join(env_db, 'pos_data.db') if os.path.isdir(env_db) else env_db
        os.makedirs(os.path.dirname(p), exist_ok=True)
        return p
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        return os.path.join(exe_dir, 'pos_data.db')
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'pos_data.db')

DB_PATH = _get_db_path()


def get_conn():
    return db.get_conn()


def _sql_type(field):
    return db.sql_type(type(field).__name__)


def _ensure_table(model_class):
    conn = get_conn()
    try:
        table = model_class._name
        exists = table in db.get_tables(conn)
        if exists:
            _migrate_table(conn, model_class)
            return

        pk = 'id SERIAL PRIMARY KEY' if db._use_pg else 'id INTEGER PRIMARY KEY AUTOINCREMENT'
        cols = [pk]
        for fname, field in model_class._fields.items():
            if fname == 'id':
                continue
            st = _sql_type(field)
            if st is None:
                continue
            nullable = ' NOT NULL' if getattr(field, 'required', False) else ''
            cols.append(f'"{fname}" {st}{nullable}')
        cols.append('"create_date" TEXT')
        cols.append('"write_date" TEXT')
        cols.append('"create_uid" INTEGER')
        cols.append('"write_uid" INTEGER')

        db.create_table(conn, table, cols)

        for fname, field in model_class._fields.items():
            if isinstance(field, Many2many):
                rel = field.rel or f'{table}_{field.comodel_name}_rel'
                col1 = field.column1 or f'{table}_id'
                col2 = field.column2 or f'{field.comodel_name}_id'
                db.create_m2m_table(conn, rel, col1, col2)
    finally:
        conn.close()


def _migrate_table(conn, model_class):
    table = model_class._name
    existing = db.get_table_columns(conn, table)
    for fname, field in model_class._fields.items():
        if fname == 'id':
            continue
        if fname not in existing:
            st = _sql_type(field)
            if st is None:
                continue
            db.add_column(conn, table, fname, st)
        elif db._use_pg and isinstance(field, Boolean):
            db.ensure_bool_column_type(conn, table, fname)


def _load_cache():
    global _db_cache
    conn = get_conn()
    try:
        tables = db.get_tables(conn)
        for table in tables:
            _db_cache.setdefault(table, {'_seq': 0, '_data': OrderedDict()})
            cached = redis_cache.all_records(table)
            if cached and table != 'product.product':
                _db_cache[table]['_data'] = cached
                _db_cache[table]['_seq'] = max(cached.keys()) if cached else 0
            else:
                exclude = 'image' if table == 'product.product' else None
                rows = db.load_table(conn, table, exclude=exclude)
                for data in rows:
                    rid = data.pop('id')
                    _db_cache[table]['_data'][rid] = data
                    if rid > _db_cache[table]['_seq']:
                        _db_cache[table]['_seq'] = rid
                for rid, rdata in _db_cache[table]['_data'].items():
                    rdata_to_save = {k: v for k, v in rdata.items() if k != 'image'} if table == 'product.product' else dict(rdata)
                    redis_cache.set(table, rid, rdata_to_save)
        _migrate_data(conn)
    finally:
        conn.close()


def _migrate_data(conn):
    if not db._use_pg:
        return
    table = 'pos.order'
    if table not in _db_cache:
        return
    dirty = False
    for rid, data in list(_db_cache[table]['_data'].items()):
        if data.get('state') == 'draft':
            _db_cache[table]['_data'][rid]['state'] = 'paid'
            redis_cache.set(table, rid, dict(_db_cache[table]['_data'][rid]))
            dirty = True
    if dirty:
        cur = conn.cursor()
        cur.execute(f'UPDATE "{table}" SET "state"=\'paid\' WHERE "state"=\'draft\'')
        db.commit(conn)


def _persist_write(cls, obj_id):
    table = cls._name
    data = dict(_db_cache[table]['_data'][obj_id])
    conn = get_conn()
    try:
        cols = {}
        for k, v in data.items():
            if k == 'id':
                continue
            field = cls._fields.get(k)
            if field and isinstance(field, (One2many, Many2many)):
                continue
            if isinstance(v, bool):
                v = 1 if v else 0
            cols[k] = v
        if not cols:
            return
        db.insert_or_update(conn, table, cols, obj_id)
        db.commit(conn)
    except Exception as e:
        import traceback
        print(f'SQL ERROR ({table}): {e}')
        traceback.print_exc()
        raise
    finally:
        conn.close()


def _persist_delete(cls, obj_id):
    table = cls._name
    conn = get_conn()
    try:
        db.delete_row(conn, table, obj_id)
        db.commit(conn)
    finally:
        conn.close()


def _persist_m2m(cls, obj_id, field_name, target_ids):
    field = cls._fields[field_name]
    rel = field.rel or f'{cls._name}_{field.comodel_name}_rel'
    col1 = field.column1 or f'{cls._name}_id'
    col2 = field.column2 or f'{field.comodel_name}_id'
    conn = get_conn()
    try:
        db.insert_m2m(conn, rel, col1, col2, obj_id, target_ids)
        db.commit(conn)
    finally:
        conn.close()


def _load_m2m(cls, obj_id, field_name):
    field = cls._fields[field_name]
    rel = field.rel or f'{cls._name}_{field.comodel_name}_rel'
    col1 = field.column1 or f'{cls._name}_id'
    col2 = field.column2 or f'{field.comodel_name}_id'
    conn = get_conn()
    try:
        return db.load_m2m(conn, rel, col1, col2, obj_id)
    finally:
        conn.close()



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


class Integer(Field):
    def convert(self, value):
        return int(value) if value is not None else value


class Float(Field):
    def __init__(self, digits=None, **kwargs):
        super().__init__(**kwargs)
        self.digits = digits

    def convert(self, value):
        return float(value) if value is not None else 0.0


class Boolean(Field):
    def convert(self, value):
        return bool(value) if value is not None else False


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
        col2 = field.column2 or f'{field.comodel_name}_id'
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
        for fname, value in list(vals.items()):
            if fname in self._fields and isinstance(self._fields[fname], Many2many):
                target_ids = [int(getattr(v, 'id', v)) for v in (value or [])]
                _persist_m2m(self.__class__, self.id, fname, target_ids)
        return True

    def _save(self):
        tbl = _db_cache[self._name]
        tbl['_data'][self.id] = dict(self._data)
        rdata = {k: v for k, v in self._data.items() if k != 'image'} if self._name == 'product.product' else dict(self._data)
        redis_cache.set(self._name, self.id, rdata)
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
                field = self._fields[fname]
                if isinstance(field, Many2many):
                    m2m_ids = _load_m2m(self.__class__, self.id, fname)
                    result[fname] = m2m_ids
                else:
                    val = self._data.get(fname)
                    if isinstance(field, Many2one) and val:
                        comodel = field.comodel_name
                        if comodel in _db_cache:
                            name = _db_cache[comodel]['_data'].get(val, {}).get(self._rec_name, '')
                            result[fname] = {'id': val, 'name': str(name)}
                        else:
                            result[fname] = val
                    else:
                        result[fname] = val
        return result

    def name_get(self):
        name = self._data.get(self._rec_name, f'[{self._name} {self.id}]')
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
        rdata = {k: v for k, v in data.items() if k != 'image'} if cls._name == 'product.product' else dict(data)
        redis_cache.set(cls._name, new_id, rdata)
        _persist_write(cls, new_id)
        obj = cls(**data)
        obj.id = new_id
        for fname in cls._fields:
            if isinstance(cls._fields[fname], Many2many) and fname in vals:
                target_ids = [int(getattr(v, 'id', v)) for v in (vals[fname] or [])]
                _persist_m2m(cls, new_id, fname, target_ids)
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
    def _reload_from_db(cls, ids=None):
        if not db._use_pg:
            return
        tbl = _db_cache.setdefault(cls._name, {'_seq': 0, '_data': OrderedDict()})
        exclude = 'image' if cls._name == 'product.product' else None
        if ids:
            for rid in ids:
                data = redis_cache.get(cls._name, rid)
                if data:
                    data = dict(data)
                    if rid in tbl['_data']:
                        old = tbl['_data'][rid]
                        for k, v in data.items():
                            old[k] = v
                    else:
                        tbl['_data'][rid] = data
                else:
                    conn = get_conn()
                    try:
                        rows = db.load_rows(conn, cls._name, [rid], exclude=exclude)
                        if rows:
                            data = rows[0]
                            data.pop('id')
                            if rid in tbl['_data']:
                                old = tbl['_data'][rid]
                                for k, v in data.items():
                                    old[k] = v
                            else:
                                tbl['_data'][rid] = data
                            redis_cache.set(cls._name, rid, dict(tbl['_data'][rid]))
                    finally:
                        conn.close()
        else:
            cached = redis_cache.all_records(cls._name)
            if cached:
                old_data = tbl['_data']
                tbl['_data'] = cached
                if exclude:
                    for rid, rdata in tbl['_data'].items():
                        if rid in old_data and exclude in old_data[rid]:
                            rdata[exclude] = old_data[rid][exclude]
                tbl['_seq'] = max(cached.keys()) if cached else 0
            else:
                conn = get_conn()
                try:
                    rows = db.load_table(conn, cls._name, exclude=exclude)
                    for data in rows:
                        rid = data.pop('id')
                        if rid in tbl['_data']:
                            old = tbl['_data'][rid]
                            for k, v in data.items():
                                old[k] = v
                        else:
                            tbl['_data'][rid] = data
                        if rid > tbl['_seq']:
                            tbl['_seq'] = rid
                    for rid, rdata in tbl['_data'].items():
                        redis_cache.set(cls._name, rid, dict(rdata))
                finally:
                    conn.close()

    @classmethod
    def browse(cls, ids):
        if isinstance(ids, int):
            ids = [ids]
        tbl = _db_cache.get(cls._name, {'_data': OrderedDict()})
        results = []
        missing = []
        for rid in ids:
            if rid in tbl['_data']:
                obj = cls(**tbl['_data'][rid])
                obj.id = rid
                results.append(obj)
            else:
                missing.append(rid)
        if missing and db._use_pg:
            rows = db.load_rows(get_conn(), cls._name, missing)
            for data in rows:
                rid = data.pop('id')
                tbl['_data'][rid] = data
                obj = cls(**data)
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
            return cls._check_child_of(data, field, value)  # noqa: F821
        return True

    @classmethod
    def _check_child_of(cls, data, field, value):
        parent_field = f'{field}_id'
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
            conn.execute(f'DELETE FROM "{cls._name}"')
            conn.commit()
        finally:
            conn.close()


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
