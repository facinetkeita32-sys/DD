from ..odoo_orm import Model, Char, Float, Many2one, Selection, DateTime
from datetime import datetime


class InventoryTransaction(Model):
    _name = 'inventory.transaction'
    _description = 'Inventory Transaction'
    _rec_name = 'id'
    _order = 'id desc'

    product_id = Many2one('product.product', string='Product', required=True)
    transaction_type = Selection([
        ('PURCHASE_RECEIPT', 'Purchase Receipt'),
        ('SALE', 'Sale'),
        ('ADJUSTMENT', 'Adjustment'),
    ], string='Type', default='PURCHASE_RECEIPT')
    quantity_change = Float(string='Quantity Change', digits=(16, 2), default=0.0)
    quantity_before = Float(string='Quantity Before', digits=(16, 2), default=0.0)
    quantity_after = Float(string='Quantity After', digits=(16, 2), default=0.0)
    unit_cost = Float(string='Unit Cost', digits=(16, 2), default=0.0)
    reference = Char(string='Reference')
    purchase_id = Many2one('purchase.order', string='Purchase Order')
    date = DateTime(string='Date', default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
