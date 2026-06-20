from ..odoo_orm import Model, Char, Float, Selection, Text, Date


class InventoryItem(Model):
    _name = 'inventory.item'
    _description = 'Inventory Item'
    _rec_name = 'name'
    _order = 'id desc'

    name = Char(string='Product Name', required=True)
    barcode = Char(string='Barcode')
    quantity = Float(string='Quantity', digits=(16, 2), default=0.0)
    cost_price = Float(string='Cost Price', digits=(16, 2), default=0.0)
    selling_price = Float(string='Selling Price', digits=(16, 2), default=0.0)
    category = Char(string='Category')
    notes = Text(string='Notes')
    date = Date(string='Date')
    status = Selection([
        ('draft', 'Draft'),
        ('verified', 'Verified'),
    ], string='Status', default='draft')
