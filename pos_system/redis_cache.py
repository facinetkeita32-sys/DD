"""
Shared Redis cache for multi-worker cache coherence.

Structure in Redis:
  cache:<table>:seq     -> integer (next ID)
  cache:<table>:data    -> hash (field=record_id, value=JSON)

Falls back to local dict if Redis is unavailable.
"""
import os
import json
from collections import OrderedDict

REDIS_URL = os.environ.get('REDIS_URL', '')
_redis = None
_local_cache = {}

if REDIS_URL:
    try:
        import redis as _redis_mod
        _redis = _redis_mod.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        _redis.ping()
    except Exception:
        _redis = None


def _key(table, kind):
    return f'cache:{table}:{kind}'


def _table_cache(table):
    if table not in _local_cache:
        _local_cache[table] = {'_seq': 0, '_data': OrderedDict()}
    return _local_cache[table]


def seq_next(table):
    """Get and increment the sequence for a table."""
    if _redis:
        try:
            return _redis.hincrby(_key(table, 'meta'), 'seq', 1)
        except Exception:
            pass
    tc = _table_cache(table)
    tc['_seq'] += 1
    return tc['_seq']


def seq_set(table, value):
    if _redis:
        try:
            _redis.hset(_key(table, 'meta'), 'seq', value)
        except Exception:
            pass
    _table_cache(table)['_seq'] = value


def seq_get(table):
    if _redis:
        try:
            val = _redis.hget(_key(table, 'meta'), 'seq')
            if val is not None:
                return int(val)
        except Exception:
            pass
    return _table_cache(table)['_seq']


def has(table, rid):
    if _redis:
        try:
            return _redis.hexists(_key(table, 'data'), rid)
        except Exception:
            pass
    tc = _table_cache(table)
    return rid in tc['_data']


def get(table, rid):
    if _redis:
        try:
            raw = _redis.hget(_key(table, 'data'), rid)
            if raw is not None:
                return json.loads(raw)
        except Exception:
            pass
    tc = _table_cache(table)
    data = tc['_data'].get(rid)
    return data


def set(table, rid, data):
    if _redis:
        try:
            _redis.hset(_key(table, 'data'), rid, json.dumps(data))
        except Exception:
            pass
    tc = _table_cache(table)
    tc['_data'][rid] = data


def delete(table, rid):
    if _redis:
        try:
            _redis.hdel(_key(table, 'data'), rid)
        except Exception:
            pass
    tc = _table_cache(table)
    tc['_data'].pop(rid, None)


def all_records(table):
    """Return OrderedDict of {id: data} for the table."""
    if _redis:
        try:
            raw = _redis.hgetall(_key(table, 'data'))
            if raw:
                result = OrderedDict()
                for k, v in raw.items():
                    result[int(k)] = json.loads(v)
                return result
        except Exception:
            pass
    return _table_cache(table)['_data']


def load_table_into_redis(table, rows):
    """Bulk load rows from DB into Redis."""
    if not _redis:
        tc = _table_cache(table)
        max_id = 0
        for data in rows:
            rid = data.pop('id')
            tc['_data'][rid] = data
            if rid > max_id:
                max_id = rid
        tc['_seq'] = max_id
        return
    try:
        pipe = _redis.pipeline()
        meta_key = _key(table, 'meta')
        data_key = _key(table, 'data')
        max_id = 0
        for data in rows:
            rid = data.pop('id')
            pipe.hset(data_key, rid, json.dumps(data))
            if rid > max_id:
                max_id = rid
        pipe.hset(meta_key, 'seq', max_id)
        pipe.execute()
    except Exception:
        pass


def keys(table):
    """Return all record IDs for a table."""
    if _redis:
        try:
            raw = _redis.hkeys(_key(table, 'data'))
            return [int(k) for k in raw]
        except Exception:
            pass
    return list(_table_cache(table)['_data'].keys())
