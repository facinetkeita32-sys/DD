PERMISSIONS = {
    'admin': {
        'screens': ['pos', 'products', 'orders', 'customers', 'sessions', 'reports', 'dashboard', 'settings', 'users', 'activity', 'inventory'],
        'actions': ['product.create', 'product.write', 'product.delete',
                    'customer.create', 'customer.write', 'customer.delete',
                    'order.create', 'order.write', 'order.cancel',
                    'session.open', 'session.close',
                    'user.create', 'user.write', 'user.delete', 'user.read',
                    'settings.read', 'settings.write',
                    'report.read',
                    'bulk.import',
                    'inventory.create', 'inventory.write', 'inventory.delete', 'inventory.import', 'inventory.export'],
    },
    'manager': {
        'screens': ['pos', 'products', 'orders', 'customers', 'sessions', 'reports', 'dashboard', 'inventory'],
        'actions': ['product.create', 'product.write', 'product.delete',
                    'customer.create', 'customer.write',
                    'order.create', 'order.write', 'order.cancel',
                    'session.open', 'session.close',
                    'report.read',
                    'bulk.import',
                    'inventory.export'],
    },
    'cashier': {
        'screens': ['pos', 'orders', 'customers', 'sessions', 'dashboard'],
        'actions': ['customer.create',
                    'order.create', 'order.write',
                    'session.open', 'session.close',
                    'report.read'],
    },
}


def role_has_permission(role, permission):
    perms = PERMISSIONS.get(role, {})
    if permission in perms.get('actions', []):
        return True
    return False


def role_has_screen(role, screen):
    screens = PERMISSIONS.get(role, {}).get('screens', [])
    return screen in screens


def get_role_screens(role):
    return PERMISSIONS.get(role, {}).get('screens', [])


def get_role_actions(role):
    return PERMISSIONS.get(role, {}).get('actions', [])
