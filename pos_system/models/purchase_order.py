from ..odoo_orm import Model, Char, Text, Float, Many2one, Selection, Date, DateTime
from datetime import datetime


class PurchaseOrder(Model):
    _name = 'purchase.order'
    _description = 'Purchase Order'
    _rec_name = 'name'
    _order = 'id desc'

    name = Char(string='Purchase Number', required=True, default='PO-TMP')
    supplier_id = Many2one('res.partner', string='Supplier')
    purchase_date = Date(string='Purchase Date', default=lambda: datetime.now().strftime('%Y-%m-%d'))
    expected_date = Date(string='Expected Delivery Date')
    invoice_reference = Char(string='Invoice Reference')
    currency_id = Many2one('res.currency', string='Currency')
    status = Selection([
        ('draft', 'Draft'),
        ('ordered', 'Ordered'),
        ('partially_received', 'Partially Received'),
        ('received', 'Received'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft')
    subtotal = Float(string='Subtotal', digits=(16, 2), default=0.0)
    additional_cost = Float(string='Additional Cost', digits=(16, 2), default=0.0)
    discount = Float(string='Discount', digits=(16, 2), default=0.0)
    grand_total = Float(string='Grand Total', digits=(16, 2), default=0.0)
    notes = Text(string='Notes')
    created_by = Many2one('res.users', string='Created By')
