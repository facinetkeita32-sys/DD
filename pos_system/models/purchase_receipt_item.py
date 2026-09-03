from ..odoo_orm import Model, Float, Many2one


class PurchaseReceiptItem(Model):
    _name = 'purchase.receipt.item'
    _description = 'Purchase Receipt Item'
    _rec_name = 'id'
    _order = 'id'

    receipt_id = Many2one('purchase.receipt', string='Receipt', required=True)
    purchase_item_id = Many2one('purchase.item', string='Purchase Item', required=True)
    product_id = Many2one('product.product', string='Product', required=True)
    quantity_received = Float(string='Quantity Received', digits=(16, 2), default=0.0)
    unit_cost = Float(string='Unit Cost', digits=(16, 2), default=0.0)
    stock_before = Float(string='Stock Before', digits=(16, 2), default=0.0)
    stock_after = Float(string='Stock After', digits=(16, 2), default=0.0)
