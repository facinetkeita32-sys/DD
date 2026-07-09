from ..odoo_orm import Model, Char, Text, Many2one, One2many, Boolean, Integer


class ProductCategory(Model):
    _name = 'product.category'
    _description = 'Product Category'
    _rec_name = 'name'
    _order = 'name'

    name = Char(string='Name', required=True)
    parent_id = Many2one('product.category', string='Parent Category')
    child_ids = One2many('product.category', 'parent_id', string='Child Categories')
    description = Text(string='Description')
    active = Boolean(string='Active', default=True)
    sequence = Integer(string='Sequence', default=10)

    def _init_defaults(self):
        categories = [
            {'name': 'All Products', 'sequence': 1},
            {'name': 'Food & Beverages', 'sequence': 10},
            {'name': 'Electronics', 'sequence': 20},
            {'name': 'Clothing', 'sequence': 30},
            {'name': 'Health & Beauty', 'sequence': 40},
            {'name': 'Stationery', 'sequence': 50},
        ]
        for cat in categories:
            existing = self.search([('name', '=', cat['name']), ('parent_id', '=', False)])
            if not existing:
                self.create(cat)



