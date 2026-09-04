from ..odoo_orm import Model, Char, Many2one, DateTime
from datetime import datetime


class LoginLog(Model):
    _name = 'login.log'
    _description = 'Login / Activity Log'
    _rec_name = 'action'
    _order = 'timestamp desc'

    user_id = Many2one('res.users', string='User', required=True)
    action = Char(string='Action', required=True)
    details = Char(string='Details')
    timestamp = DateTime(string='Timestamp', default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    ip_address = Char(string='IP Address')
