from ..odoo_orm import Model, Char, Integer, Boolean


class BackupSettings(Model):
    _name = 'backup.settings'
    _description = 'Backup Settings'

    url = Char(string='Backup Server URL')
    api_key = Char(string='API Key')
    interval_minutes = Integer(string='Interval', default=60)
    auto_backup = Boolean(string='Automatic Backup', default=False)
