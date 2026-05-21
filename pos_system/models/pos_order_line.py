from ..odoo_orm import Model, Many2one, Many2many, Float, Char


class PosOrderLine(Model):
    _name = 'pos.order.line'
    _description = 'POS Order Line'
    _rec_name = 'product_id'
    _order = 'id'

    order_id = Many2one('pos.order', string='Order', required=True)
    product_id = Many2one('product.product', string='Product', required=True)
    product_name = Char(string='Product Name')
    qty = Float(string='Quantity', digits=(16, 3), default=1.0)
    price_unit = Float(string='Unit Price', digits=(16, 2), default=0.0)
    discount = Float(string='Discount (%)', digits=(5, 2), default=0.0)
    price_subtotal = Float(string='Subtotal', digits=(16, 2), default=0.0)
    price_subtotal_incl = Float(string='Subtotal Incl. Tax', digits=(16, 2), default=0.0)
    tax_ids = Many2many('pos.tax', string='Taxes')

    def compute_subtotal(self):
        line_total = self.qty * self.price_unit
        discount_amount = line_total * (self.discount / 100)
        self.price_subtotal = line_total - discount_amount
        return self.price_subtotal



