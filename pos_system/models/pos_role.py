import json
from ..odoo_orm import Model, Char, env


class PosRole(Model):
    _name = 'pos.role'
    _description = 'Roles'
    _rec_name = 'name'

    name = Char(string='Role Name', required=True)
    key = Char(string='Key', required=True)
    screens = Char(string='Screens', default='[]')
    actions = Char(string='Actions', default='[]')

    def get_screens(self):
        try:
            return json.loads(self.screens or '[]')
        except (json.JSONDecodeError, TypeError):
            return []

    def get_actions(self):
        try:
            return json.loads(self.actions or '[]')
        except (json.JSONDecodeError, TypeError):
            return []

    def _init_defaults(self):
        from ..permissions import PERMISSIONS
        for key, perms in PERMISSIONS.items():
            existing = self.search([('key', '=', key)])
            if not existing:
                self.create({
                    'name': key.capitalize(),
                    'key': key,
                    'screens': json.dumps(perms.get('screens', [])),
                    'actions': json.dumps(perms.get('actions', [])),
                })
