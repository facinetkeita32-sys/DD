from ..odoo_orm import Model, Char, Many2one, Boolean, Integer


class PosCategory(Model):
    _name = 'pos.category'
    _description = 'POS Category'
    _rec_name = 'name'
    _order = 'sequence, name'

    name = Char(string='Name', required=True)
    parent_id = Many2one('pos.category', string='Parent Category')
    sequence = Integer(string='Sequence', default=10)
    active = Boolean(string='Active', default=True)
    color = Integer(string='Color Index', default=0)

    def _init_defaults(self):
        categories = [
            {'name': 'All', 'sequence': 1, 'color': 1},
            {'name': 'Beverages', 'sequence': 10, 'color': 2},
            {'name': 'Food', 'sequence': 20, 'color': 3},
            {'name': 'Snacks', 'sequence': 30, 'color': 4},
        ]
        for cat in categories:
            existing = self.search([('name', '=', cat['name'])])
            if not existing:
                self.create(cat)
