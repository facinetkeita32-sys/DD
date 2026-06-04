from datetime import datetime
from ..odoo_orm import Model, Char, Many2one, DateTime


class LoginLog(Model):
    _name = 'login.log'
    _description = 'Login/Logout Log'
    _order = 'timestamp desc'
    _rec_name = 'action'

    user_id = Many2one('res.users', string='User', required=True)
    action = Char(string='Action', required=True)
    timestamp = DateTime(string='Timestamp', default=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    ip_address = Char(string='IP Address')
