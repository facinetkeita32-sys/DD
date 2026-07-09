from ..odoo_orm import Model, Char, Float, Integer, Selection, Boolean


class ResCurrency(Model):
    _name = 'res.currency'
    _description = 'Currency'
    _rec_name = 'name'
    _order = 'name'

    name = Char(string='Name', required=True)
    symbol = Char(string='Symbol', required=True)
    iso_code = Char(string='ISO Code', size=3, required=True)
    decimal_places = Integer(string='Decimal Places', default=2)
    active = Boolean(string='Active', default=True)
    position = Selection([
        ('before', 'Before Amount'),
        ('after', 'After Amount'),
    ], string='Symbol Position', default='before')
    rate = Float(string='Rate', digits=(16, 6), default=1.0)

    def _init_defaults(self):
        currencies = [
            {'name': 'Guinean Franc', 'symbol': 'FG', 'iso_code': 'GNF', 'decimal_places': 0, 'active': True, 'position': 'before', 'rate': 1.0},
            {'name': 'US Dollar', 'symbol': '$', 'iso_code': 'USD', 'decimal_places': 2, 'active': True, 'position': 'before', 'rate': 8600.0},
            {'name': 'Euro', 'symbol': '€', 'iso_code': 'EUR', 'decimal_places': 2, 'active': True, 'position': 'before', 'rate': 9400.0},
            {'name': 'CFA Franc', 'symbol': 'CFA', 'iso_code': 'XOF', 'decimal_places': 0, 'active': True, 'position': 'after', 'rate': 14.2},
        ]
        for cur in currencies:
            existing = self.search([('iso_code', '=', cur['iso_code'])])
            if not existing:
                self.create(cur)
