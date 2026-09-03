from ..odoo_orm import Model, Char, Many2one, DateTime
from datetime import datetime


class PurchaseReceipt(Model):
    _name = 'purchase.receipt'
    _description = 'Purchase Receipt'
    _rec_name = 'name'
    _order = 'id desc'

    name = Char(string='Receipt Number', required=True, default='RCV-TMP')
    purchase_id = Many2one('purchase.order', string='Purchase Order', required=True)
    received_at = DateTime(string='Received At', default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    created_by = Many2one('res.users', string='Created By')
