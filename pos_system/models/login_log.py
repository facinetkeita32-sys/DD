from datetime import datetime
from ..odoo_orm import Model, Integer, Char, DateTime, Text


class LoginLog(Model):
    _name = 'login.log'
    user_id = Integer()
    action = Char()
    details = Char()
    model = Char()
    message = Text()
    timestamp = DateTime(default=lambda: datetime.now())
    ip_address = Char()
