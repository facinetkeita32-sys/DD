from datetime import datetime
from ..odoo_orm import Model, Char, Many2one, Float, Date, DateTime, Integer, env


class StockLot(Model):
    _name = 'stock.lot'
    _description = 'Product Batch/Lot'
    _rec_name = 'name'
    _order = 'expiration_date asc, id asc'

    name = Char(string='Batch Number', required=True)
    product_id = Many2one('product.product', string='Product', required=True)
    qty = Float(string='Quantity', digits=(16, 2), default=0.0)
    qty_available = Float(string='Available Quantity', digits=(16, 2), default=0.0)
    purchase_date = Date(string='Purchase Date')
    expiration_date = Date(string='Expiration Date')
    supplier = Char(string='Supplier')
    cost_price = Float(string='Cost Price', digits=(16, 2), default=0.0)
    sale_price = Float(string='Sale Price', digits=(16, 2), default=0.0)
    active = Char(string='Active', default='True')

    @classmethod
    def deduct_fefo(cls, product_id, qty_needed):
        lots = cls().search([
            ('product_id', '=', product_id),
            ('qty_available', '>', 0),
        ], order='expiration_date asc nulls last, id asc')
        remaining = qty_needed
        for lot in lots:
            if remaining <= 0:
                break
            avail = lot.qty_available or 0
            if avail <= 0:
                continue
            take = min(avail, remaining)
            lot.write({'qty_available': round(avail - take, 2)})
            remaining = round(remaining - take, 2)
        product = env['product.product'].browse([product_id])
        if product:
            total = sum(l.qty_available or 0 for l in lots)
            product[0].write({'available_qty': round(total, 2)})
        return qty_needed - remaining

    @classmethod
    def restore_qty(cls, product_id, qty):
        lots = cls().search([
            ('product_id', '=', product_id),
            ('qty', '>', 0),
        ], order='id desc')
        remaining = qty
        for lot in lots:
            if remaining <= 0:
                break
            orig = lot.qty or 0
            current = lot.qty_available or 0
            can_add = orig - current
            if can_add <= 0:
                continue
            take = min(can_add, remaining)
            lot.write({'qty_available': round(current + take, 2)})
            remaining = round(remaining - take, 2)
        product = env['product.product'].browse([product_id])
        if product:
            total = sum(l.qty_available or 0 for l in lots)
            product[0].write({'available_qty': round(total, 2)})

    @classmethod
    def recompute_product_qty(cls, product_id):
        lots = cls().search([('product_id', '=', product_id)])
        total = sum(l.qty_available or 0 for l in lots)
        product = env['product.product'].browse([product_id])
        if product:
            product[0].write({'available_qty': round(total, 2)})
