from ..odoo_orm import Model, Char, Float, Many2one


class PurchaseItem(Model):
    _name = 'purchase.item'
    _description = 'Purchase Item'
    _rec_name = 'product_name'
    _order = 'id'

    purchase_id = Many2one('purchase.order', string='Purchase Order', required=True)
    product_id = Many2one('product.product', string='Product')
    pending_product_id = Many2one('pending.product', string='Pending Product')
    product_name = Char(string='Product Name')
    sku = Char(string='SKU')
    barcode = Char(string='Barcode')
    quantity_ordered = Float(string='Quantity Ordered', digits=(16, 2), default=0.0)
    quantity_received = Float(string='Quantity Received', digits=(16, 2), default=0.0)
    unit_cost = Float(string='Unit Cost', digits=(16, 2), default=0.0)
    selling_price = Float(string='Selling Price', digits=(16, 2), default=0.0)
    line_total = Float(string='Line Total', digits=(16, 2), default=0.0)
