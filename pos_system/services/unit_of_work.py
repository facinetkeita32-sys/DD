"""Opt-in transactions for offline operations; normal ORM calls are unchanged."""
import copy
from contextlib import contextmanager

from .. import db
from ..odoo_orm import _db_cache, _db_lock


class BorrowedConnection:
    def __init__(self, connection):
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def close(self):
        pass

    def commit(self):
        pass


@contextmanager
def atomic():
    if db._transaction_connection.get() is not None:
        yield db.get_conn()
        return
    with _db_lock:
        before = copy.deepcopy(_db_cache)
        connection = db.get_conn()
        token = None
        try:
            if db._use_pg:
                connection.autocommit = False
            else:
                connection.execute('BEGIN IMMEDIATE')
            token = db._transaction_connection.set(BorrowedConnection(connection))
            yield db.get_conn()
            connection.commit()
        except BaseException:
            connection.rollback()
            _db_cache.clear()
            _db_cache.update(before)
            raise
        finally:
            if token is not None:
                db._transaction_connection.reset(token)
            connection.close()
