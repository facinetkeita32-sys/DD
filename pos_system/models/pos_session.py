from ..odoo_orm import Model, Char, Many2one, Boolean, DateTime, Float, Selection, Integer


class PosSession(Model):
    _name = 'pos.session'
    _description = 'POS Session'
    _rec_name = 'name'
    _order = 'id desc'

    name = Char(string='Session', required=True)
    user_id = Many2one('res.users', string='User', required=True)
    config_id = Many2one('pos.config', string='POS Configuration')
    state = Selection([
        ('opening_control', 'Opening Control'),
        ('opened', 'Opened'),
        ('closing_control', 'Closing Control'),
        ('closed', 'Closed'),
    ], string='Status', default='opening_control')
    start_at = DateTime(string='Start Date')
    stop_at = DateTime(string='End Date')
    cash_register_balance_start = Float(string='Opening Cash', digits=(16, 2), default=0.0)
    cash_register_balance_end = Float(string='Closing Cash', digits=(16, 2), default=0.0)
    total_sales = Float(string='Total Sales', digits=(16, 2), default=0.0)
    total_orders = Integer(string='Total Orders', default=0)
    active = Boolean(string='Active', default=True)

    def action_open(self):
        from datetime import datetime
        self.write({
            'state': 'opened',
            'start_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })

    def action_close(self):
        from datetime import datetime
        from ..odoo_orm import env
        orders = env['pos.order'].search([('session_id', '=', self.id)])
        total = sum(o.amount_total for o in orders)
        count = len(orders)
        self.write({
            'state': 'closed',
            'stop_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'total_sales': total,
            'total_orders': count,
        })
