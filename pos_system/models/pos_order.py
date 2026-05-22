from ..odoo_orm import Model, Char, Many2one, DateTime, Float, Selection, Integer, Text, One2many
from datetime import datetime


class PosOrder(Model):
    _name = 'pos.order'
    _description = 'POS Order'
    _rec_name = 'name'
    _order = 'id desc'

    name = Char(string='Order Reference', required=True)
    date_order = DateTime(string='Order Date', default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    partner_id = Many2one('res.partner', string='Customer')
    user_id = Many2one('res.users', string='Cashier', required=True)
    session_id = Many2one('pos.session', string='Session')
    company_id = Many2one('res.company', string='Company')
    lines = One2many('pos.order.line', 'order_id', string='Order Lines')
    payment_ids = One2many('pos.payment', 'order_id', string='Payments')
    amount_total = Float(string='Total Amount', digits=(16, 2), default=0.0)
    amount_tax = Float(string='Tax Amount', digits=(16, 2), default=0.0)
    amount_paid = Float(string='Amount Paid', digits=(16, 2), default=0.0)
    amount_change = Float(string='Change', digits=(16, 2), default=0.0)
    state = Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending Payment'),
        ('paid', 'Paid'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    ], string='Status', default='draft')
    delivery_zone_id = Many2one('delivery.zone', string='Delivery Zone')
    delivery_cost = Float(string='Delivery Cost', digits=(16, 2), default=0.0)
    delivery_contact_name = Char(string='Delivery Contact Name')
    delivery_contact_phone = Char(string='Delivery Contact Phone')
    note = Text(string='Note')
    pos_reference = Char(string='POS Reference')

    def action_paid(self):
        self.write({'state': 'paid', 'amount_paid': self.amount_total})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancelled'})

    def compute_all(self):
        total = 0
        tax = 0
        for line in self.env['pos.order.line'].search([('order_id', '=', self.id)]):
            line_total = line.qty * line.price_unit
            disc = line_total * (line.discount / 100)
            subtotal = line_total - disc
            line.price_subtotal = subtotal
            total += subtotal
        self.amount_total = total
        self.amount_tax = tax
        return total
