from ..odoo_orm import Model, Char, Float, Many2one, Selection, Boolean


class PendingProduct(Model):
    _name = 'pending.product'
    _description = 'Pending Product'
    _rec_name = 'name'
    _order = 'id desc'

    name = Char(string='Name', required=True)
    category = Char(string='Category')
    sku = Char(string='SKU')
    barcode = Char(string='Barcode')
    unit_cost = Float(string='Unit Cost', digits=(16, 2), default=0.0)
    selling_price = Float(string='Selling Price', digits=(16, 2), default=0.0)
    quantity = Float(string='Quantity', digits=(16, 2), default=0.0)
    supplier_id = Many2one('res.partner', string='Supplier')
    active = Boolean(string='Active', default=True)
    status = Selection([
        ('pending', 'Pending'),
        ('received', 'Received'),
    ], string='Status', default='pending')
