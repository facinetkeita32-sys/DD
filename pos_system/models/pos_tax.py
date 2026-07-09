from ..odoo_orm import Model, Char, Float, Boolean, Many2one


class PosTax(Model):
    _name = 'pos.tax'
    _description = 'POS Tax'
    _rec_name = 'name'

    name = Char(string='Name', required=True)
    amount = Float(string='Amount (%)', digits=(5, 3), default=0.0)
    active = Boolean(string='Active', default=True)
    price_include = Boolean(string='Included in Price', default=False)
    company_id = Many2one('res.company', string='Company')

    def _init_defaults(self):
        taxes = [
            {'name': 'No Tax', 'amount': 0.0, 'active': True, 'price_include': False},
            {'name': 'VAT 5%', 'amount': 5.0, 'active': True, 'price_include': False},
            {'name': 'VAT 10%', 'amount': 10.0, 'active': True, 'price_include': False},
            {'name': 'VAT 18%', 'amount': 18.0, 'active': True, 'price_include': True},
        ]
        for tax in taxes:
            existing = self.search([('name', '=', tax['name'])])
            if not existing:
                self.create(tax)
