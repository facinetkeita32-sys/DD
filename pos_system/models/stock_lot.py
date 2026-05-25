from datetime import datetime
from ..odoo_orm import Model, Char, Float, Many2one, Boolean, Date


class StockLot(Model):
    _name = 'stock.lot'
    _description = 'Lot/Stock Batch'
    _rec_name = 'name'
    _order = 'expiration_date asc, id asc'

    name = Char(string='Lot Number', required=True)
    product_id = Many2one('product.product', string='Product', required=True)
    expiration_date = Date(string='Expiration Date')
    available_qty = Float(string='Quantity', digits=(16, 2), default=0.0)
    active = Boolean(string='Active', default=True)

    def _init_defaults(self):
        from .product_product import ProductProduct
        products = ProductProduct().search([])
        for p in products:
            existing = self.search([('product_id', '=', p.id)])
            if existing:
                continue
            p_qty = float(p._data.get('available_qty', 0) or 0)
            if p_qty > 0:
                self.create({
                    'name': 'BATCH-001-%s' % p.name.replace(' ', ''),
                    'product_id': p.id,
                    'available_qty': p_qty,
                })
            else:
                self.create({
                    'name': 'BATCH-A-%s' % p.name.replace(' ', ''),
                    'product_id': p.id,
                    'available_qty': 50,
                })
                self.create({
                    'name': 'BATCH-B-%s' % p.name.replace(' ', ''),
                    'product_id': p.id,
                    'available_qty': 50,
                })
            self._recompute_product_qty(p.id)

    @classmethod
    def _recompute_product_qty(cls, product_id):
        from .product_product import ProductProduct
        lots = cls.search([('product_id', '=', product_id)])
        total = sum(float(lot._data.get('available_qty', 0) or 0) for lot in lots)
        products = ProductProduct().browse([product_id])
        if products:
            products[0].write({'available_qty': total})

    @classmethod
    def deduct_fefo(cls, product_id, qty):
        lots = cls.search([('product_id', '=', product_id)])
        remaining = float(qty)
        for lot in lots:
            if remaining <= 0:
                break
            lot_qty = float(lot._data.get('available_qty', 0) or 0)
            if lot_qty <= 0:
                continue
            take = min(remaining, lot_qty)
            lot.write({'available_qty': lot_qty - take})
            remaining -= take
        cls._recompute_product_qty(product_id)
        return remaining

    @classmethod
    def restore_qty(cls, product_id, qty):
        lots = cls.search([('product_id', '=', product_id)])
        remaining = float(qty)
        if lots:
            lot = lots[0]
            lot_qty = float(lot._data.get('available_qty', 0) or 0)
            lot.write({'available_qty': lot_qty + remaining})
        else:
            from .product_product import ProductProduct
            products = ProductProduct().browse([product_id])
            pname = products[0]._data.get('name', 'Product') if products else 'Product'
            now_str = datetime.now().strftime('%Y%m%d%H%M%S')
            cls.create({
                'name': '%s-REST-%s' % (pname, now_str),
                'product_id': product_id,
                'available_qty': remaining,
            })
        cls._recompute_product_qty(product_id)
