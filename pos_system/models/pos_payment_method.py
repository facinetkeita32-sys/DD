from ..odoo_orm import Model, Char, Boolean, Selection, Many2one, Float


class PosPaymentMethod(Model):
    _name = 'pos.payment.method'
    _description = 'POS Payment Method'
    _rec_name = 'name'

    name = Char(string='Name', required=True)
    journal_id = Many2one('pos.journal', string='Journal')
    is_cash = Boolean(string='Is Cash Payment', default=False)
    is_card = Boolean(string='Is Card Payment', default=False)
    is_mobile_money = Boolean(string='Is Mobile Money', default=False)
    active = Boolean(string='Active', default=True)
    fee_percent = Float(string='Fee (%)', digits=(5, 2), default=0.0)

    def _init_defaults(self):
        methods = [
            {'name': 'Cash', 'is_cash': True, 'active': True, 'fee_percent': 0.0},
            {'name': 'Orange Money', 'is_mobile_money': True, 'active': True, 'fee_percent': 0.5},
            {'name': 'MTN Mobile Money', 'is_mobile_money': True, 'active': True, 'fee_percent': 0.5},
            {'name': 'Credit Card', 'is_card': True, 'active': True, 'fee_percent': 1.5},
            {'name': 'Bank Transfer', 'active': True, 'fee_percent': 0.0},
        ]
        for method in methods:
            existing = self.search([('name', '=', method['name'])])
            if not existing:
                self.create(method)
