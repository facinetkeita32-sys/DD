from ..odoo_orm import Model, Char, Boolean, Selection


class ResLang(Model):
    _name = 'res.lang'
    _description = 'Language'
    _rec_name = 'name'
    _order = 'name'

    name = Char(string='Name', required=True)
    code = Char(string='Code', size=5, required=True)
    active = Boolean(string='Active', default=True)
    direction = Selection([
        ('ltr', 'Left to Right'),
        ('rtl', 'Right to Left'),
    ], string='Direction', default='ltr')
    date_format = Char(string='Date Format', default='%m/%d/%Y')
    time_format = Char(string='Time Format', default='%H:%M:%S')

    def _init_defaults(self):
        langs = [
            {'name': 'English', 'code': 'en', 'active': True, 'direction': 'ltr', 'date_format': '%m/%d/%Y'},
            {'name': 'Français', 'code': 'fr', 'active': True, 'direction': 'ltr', 'date_format': '%d/%m/%Y'},
            {'name': 'Pular', 'code': 'ff', 'active': True, 'direction': 'ltr', 'date_format': '%d/%m/%Y'},
        ]
        for lang in langs:
            existing = self.search([('code', '=', lang['code'])])
            if not existing:
                self.create(lang)
