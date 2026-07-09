from ..odoo_orm import Model, Many2one, Float, Char, DateTime
from datetime import datetime


class PosPayment(Model):
    _name = 'pos.payment'
    _description = 'POS Payment'
    _rec_name = 'payment_method_id'
    _order = 'id'

    order_id = Many2one('pos.order', string='Order', required=True)
    payment_method_id = Many2one('pos.payment.method', string='Payment Method', required=True)
    amount = Float(string='Amount', digits=(16, 2), required=True)
    payment_date = DateTime(string='Payment Date', default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    reference = Char(string='Reference')
    is_change = Float(string='Change Given', digits=(16, 2), default=0.0)
