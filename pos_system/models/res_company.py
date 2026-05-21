from ..odoo_orm import Model, Char, Text, Many2one, Boolean


class ResCompany(Model):
    _name = 'res.company'
    _description = 'Company'
    _rec_name = 'name'

    name = Char(string='Company Name', required=True)
    street = Char(string='Street')
    city = Char(string='City')
    state = Char(string='State')
    zip_code = Char(string='ZIP')
    country = Char(string='Country')
    email = Char(string='Email')
    phone = Char(string='Phone')
    website = Char(string='Website')
    vat = Char(string='Tax ID')
    currency_id = Many2one('res.currency', string='Currency')
    logo = Text(string='Logo')
    receipt_header = Char(string='Receipt Header', default='Thank you for your purchase!')
    receipt_footer = Char(string='Receipt Footer', default='Have a great day!')

    def _init_defaults(self):
        existing = self.search([('name', '=', 'My Company')])
        if not existing:
            from .res_currency import ResCurrency
            gnf = ResCurrency().search([('iso_code', '=', 'GNF')], limit=1)
            self.create({
                'name': 'My Company',
                'country': 'Guinea',
                'currency_id': gnf[0].id if gnf else False,
                'receipt_header': 'Thank you for your purchase! - Shop With DD POS',
                'receipt_footer': 'Have a great day! - Merci!',
            })
