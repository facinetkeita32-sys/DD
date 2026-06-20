from ..odoo_orm import Model, Char, Text, Float, Many2one, Many2many, Boolean, Selection, Integer, Date


class ProductProduct(Model):
    _name = 'product.product'
    _description = 'Product'
    _rec_name = 'name'
    _order = 'name'

    name = Char(string='Name', required=True)
    barcode = Char(string='Barcode', size=13)
    default_code = Char(string='Internal Reference')
    description = Text(string='Description')
    description_sale = Text(string='Sale Description')
    list_price = Float(string='Sales Price', digits=(16, 2), required=True, default=0.0)
    cost_price = Float(string='Cost Price', digits=(16, 2), default=0.0)
    categ_id = Many2one('product.category', string='Category')
    type = Selection([
        ('product', 'Stockable Product'),
        ('consu', 'Consumable'),
        ('service', 'Service'),
    ], string='Product Type', default='product')
    available_qty = Float(string='Quantity on Hand', digits=(16, 2), default=0.0)
    uom_name = Char(string='Unit of Measure', default='Unit(s)')
    active = Boolean(string='Active', default=True)
    image = Text(string='Image')
    tax_ids = Many2many('pos.tax', string='Taxes')
    pos_categ_ids = Many2many('pos.category', string='POS Categories')
    track_serial = Boolean(string='Track by Serial Number', default=False)
    is_favorite = Boolean(string='Favorite', default=False)
    color = Integer(string='Color Index', default=0)
    expiration_date = Date(string='Expiration Date')

    def write(self, vals):
        if 'available_qty' in vals:
            new_qty = float(vals['available_qty'])
            from .stock_lot import StockLot
            lots = StockLot().search([('product_id', '=', self.id)])
            if lots:
                total = sum(float(l._data.get('available_qty', 0) or 0) for l in lots)
                delta = new_qty - total
                if delta != 0:
                    lot = lots[0]
                    cur = float(lot._data.get('available_qty', 0) or 0)
                    lot.write({'available_qty': max(0, cur + delta)})
            else:
                StockLot().create({
                    'name': 'BATCH-001-%s' % self._data.get('name', str(self.id)),
                    'product_id': self.id,
                    'available_qty': new_qty,
                })
        return super().write(vals)

    def _init_defaults(self):
        products = [
            {'name': 'Coffee (Small)', 'list_price': 5000, 'cost_price': 2000, 'type': 'consu', 'uom_name': 'Cup', 'available_qty': 0, 'barcode': '590001'},
            {'name': 'Coffee (Large)', 'list_price': 8000, 'cost_price': 3500, 'type': 'consu', 'uom_name': 'Cup', 'available_qty': 0, 'barcode': '590002'},
            {'name': 'Tea', 'list_price': 4000, 'cost_price': 1500, 'type': 'consu', 'uom_name': 'Cup', 'available_qty': 0, 'barcode': '590003'},
            {'name': 'Bottled Water', 'list_price': 3000, 'cost_price': 1500, 'type': 'consu', 'uom_name': 'Bottle', 'available_qty': 0, 'barcode': '590004'},
            {'name': 'Orange Juice', 'list_price': 7000, 'cost_price': 3000, 'type': 'consu', 'uom_name': 'Glass', 'available_qty': 0, 'barcode': '590005'},
            {'name': 'Croissant', 'list_price': 6000, 'cost_price': 2500, 'type': 'consu', 'uom_name': 'Piece', 'available_qty': 0, 'barcode': '590006'},
            {'name': 'Sandwich', 'list_price': 15000, 'cost_price': 7000, 'type': 'consu', 'uom_name': 'Piece', 'available_qty': 0, 'barcode': '590007'},
            {'name': 'Cake Slice', 'list_price': 10000, 'cost_price': 4500, 'type': 'consu', 'uom_name': 'Slice', 'available_qty': 0, 'barcode': '590008'},
            {'name': 'French Fries', 'list_price': 8000, 'cost_price': 3000, 'type': 'consu', 'uom_name': 'Portion', 'available_qty': 0, 'barcode': '590009'},
            {'name': 'Hamburger', 'list_price': 18000, 'cost_price': 8500, 'type': 'consu', 'uom_name': 'Piece', 'available_qty': 0, 'barcode': '590010'},
        ]
        for prod in products:
            existing = self.search([('barcode', '=', prod['barcode'])])
            if not existing:
                self.create(prod)



