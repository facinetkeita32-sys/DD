from ..odoo_orm import Model, Char, Text, Boolean, Selection, Float, Many2one, DateTime


class ResPartner(Model):
    _name = 'res.partner'
    _description = 'Partner / Customer'
    _rec_name = 'name'
    _order = 'name'

    name = Char(string='Name', required=True)
    email = Char(string='Email')
    phone = Char(string='Phone')
    mobile = Char(string='Mobile')
    street = Char(string='Street')
    city = Char(string='City')
    state = Char(string='State')
    zip_code = Char(string='ZIP')
    country = Char(string='Country')
    vat = Char(string='Tax ID')
    company_type = Selection([
        ('person', 'Individual'),
        ('company', 'Company'),
    ], string='Company Type', default='person')
    customer = Boolean(string='Is a Customer', default=True)
    supplier = Boolean(string='Is a Supplier', default=False)
    active = Boolean(string='Active', default=True)
    image = Text(string='Image')
    notes = Text(string='Notes')
    credit_limit = Float(string='Credit Limit', digits=(16, 2), default=0.0)
    total_due = Float(string='Total Due', digits=(16, 2), default=0.0)

    def _init_defaults(self):
        existing = self.search([('name', '=', 'Walk-in Customer')])
        if not existing:
            self.create({
                'name': 'Walk-in Customer',
                'customer': True,
                'active': True,
            })
