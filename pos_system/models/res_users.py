from ..odoo_orm import Model, Char, Boolean, Selection, DateTime, One2many, env


class ResUsers(Model):
    _name = 'res.users'
    _description = 'Users'
    _rec_name = 'login'

    login = Char(string='Login', required=True)
    password = Char(string='Password', required=True)
    name = Char(string='Full Name', required=True)
    email = Char(string='Email')
    active = Boolean(string='Active', default=True)
    role = Selection([
        ('admin', 'Administrator'),
        ('manager', 'Manager'),
        ('cashier', 'Cashier'),
    ], string='Role', default='cashier')
    lang = Char(string='Language', default='en')
    pin = Char(string='PIN Code', size=4)
    session_ids = One2many('pos.session', 'user_id', string='Sessions')

    def _init_defaults(self):
        existing = self.search([('login', '=', 'admin')])
        if not existing:
            self.create({
                'login': 'admin',
                'password': 'admin',
                'name': 'Administrator',
                'role': 'admin',
                'active': True,
            })
        cashier = self.search([('login', '=', 'cashier1')])
        if not cashier:
            self.create({
                'login': 'cashier1',
                'password': '1234',
                'name': 'Cashier One',
                'role': 'cashier',
                'active': True,
                'pin': '1234',
            })



