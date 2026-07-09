from ..odoo_orm import Model, Char, Float, Boolean


class DeliveryZone(Model):
    _name = 'delivery.zone'
    _description = 'Delivery Zone'
    _rec_name = 'name'
    _order = 'id'

    name = Char(string='Zone Name', required=True)
    cost = Float(string='Delivery Cost', digits=(16, 2), required=True, default=0.0)
    active = Boolean(string='Active', default=True)

    def _init_defaults(self):
        existing = self.search([], limit=1)
        if not existing:
            zones = [
                {'name': 'Zone 1', 'cost': 30000},
                {'name': 'Zone 2', 'cost': 37500},
                {'name': 'Zone 3', 'cost': 45000},
                {'name': 'Zone 4', 'cost': 52500},
                {'name': 'Zone 5', 'cost': 60000},
            ]
            for z in zones:
                self.create(z)
