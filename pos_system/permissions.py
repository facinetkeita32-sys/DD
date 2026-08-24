import json

PERMISSIONS = {
    'admin': {
        'screens': ['pos', 'products', 'orders', 'customers', 'sessions', 'reports', 'dashboard', 'settings', 'users', 'roles', 'activity'],
        'actions': ['product.create', 'product.write', 'product.delete',
                    'customer.create', 'customer.write', 'customer.delete',
                    'order.create', 'order.write', 'order.cancel',
                    'session.open', 'session.close',
                    'user.create', 'user.write', 'user.delete', 'user.read',
                    'settings.read', 'settings.write',
                    'report.read',
                    'bulk.import'],
    },
    'manager': {
        'screens': ['pos', 'products', 'orders', 'customers', 'sessions', 'reports', 'dashboard'],
        'actions': ['product.create', 'product.write', 'product.delete',
                    'customer.create', 'customer.write',
                    'order.create', 'order.write', 'order.cancel',
                    'session.open', 'session.close',
                    'report.read',
                    'bulk.import'],
    },
    'cashier': {
        'screens': ['pos', 'orders', 'customers', 'sessions', 'dashboard', 'reports'],
        'actions': ['customer.create',
                    'order.create', 'order.write',
                    'session.open', 'session.close',
                    'report.read'],
    },
}

ALL_SCREENS = ['pos', 'products', 'orders', 'customers', 'sessions', 'reports', 'dashboard', 'settings', 'users', 'activity', 'roles']
ALL_ACTIONS = ['product.create', 'product.write', 'product.delete',
               'customer.create', 'customer.write', 'customer.delete',
               'order.create', 'order.write', 'order.cancel',
               'session.open', 'session.close',
               'user.create', 'user.write', 'user.delete', 'user.read',
               'settings.read', 'settings.write',
               'report.read',
               'bulk.import']

_db_roles_cache = {}


def _load_from_db():
    global _db_roles_cache
    try:
        from .models.pos_role import PosRole
        roles = PosRole().search([])
        for r in roles:
            key = r._data.get('key', '')
            if key:
                try:
                    screens = json.loads(r._data.get('screens', '[]') or '[]')
                except (json.JSONDecodeError, TypeError):
                    screens = PERMISSIONS.get(key, {}).get('screens', [])
                try:
                    actions = json.loads(r._data.get('actions', '[]') or '[]')
                except (json.JSONDecodeError, TypeError):
                    actions = PERMISSIONS.get(key, {}).get('actions', [])
                _db_roles_cache[key] = {'screens': screens, 'actions': actions}
    except Exception:
        _db_roles_cache = {}


def _get_perms(role):
    if not _db_roles_cache:
        _load_from_db()
    if role in _db_roles_cache:
        return _db_roles_cache[role]
    return PERMISSIONS.get(role, {})


def role_has_permission(role, permission):
    perms = _get_perms(role)
    return permission in perms.get('actions', [])


def role_has_screen(role, screen):
    screens = _get_perms(role).get('screens', [])
    return screen in screens


def get_role_screens(role):
    return _get_perms(role).get('screens', [])


def get_role_actions(role):
    return _get_perms(role).get('actions', [])


def reload_permissions():
    global _db_roles_cache
    _db_roles_cache = {}
    _load_from_db()
