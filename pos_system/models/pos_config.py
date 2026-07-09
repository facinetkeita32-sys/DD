from ..odoo_orm import Model, Char, Boolean, Many2one, Many2many, Integer, Float, Selection


class PosConfig(Model):
    _name = 'pos.config'
    _description = 'POS Configuration'
    _rec_name = 'name'

    name = Char(string='Name', required=True, default='Main POS')
    company_id = Many2one('res.company', string='Company')
    active = Boolean(string='Active', default=True)
    currency_id = Many2one('res.currency', string='Currency')
    iface_available_qty = Boolean(string='Show Available Quantity', default=True)
    iface_display_categ = Boolean(string='Display Category Tabs', default=True)
    iface_print_bill = Boolean(string='Print Bill', default=True)
    iface_barcode = Boolean(string='Barcode Scanner', default=True)
    iface_search = Boolean(string='Search Products', default=True)
    limit_categories = Boolean(string='Limit Categories', default=False)
    category_ids = Many2many('pos.category', string='Available Categories')
    default_partner_id = Many2one('res.partner', string='Default Customer')
    payment_method_ids = Many2many('pos.payment.method', string='Payment Methods')
    receipt_header = Char(string='Receipt Header', default='Thank you for your purchase!')
    receipt_footer = Char(string='Receipt Footer', default='Have a great day!')
    tax_included = Boolean(string='Tax Included in Prices', default=False)
    default_lang = Char(string='Default Language', default='en')
    low_stock_threshold = Integer(string='Low Stock Threshold', default=5)

    def _init_defaults(self):
        existing = self.search([('name', '=', 'Main POS')])
        if not existing:
            from .res_currency import ResCurrency
            from .res_partner import ResPartner
            from .pos_payment_method import PosPaymentMethod
            gnf = ResCurrency().search([('iso_code', '=', 'GNF')], limit=1)
            customer = ResPartner().search([('name', '=', 'Walk-in Customer')], limit=1)
            methods = PosPaymentMethod().search([])
            self.create({
                'name': 'Main POS',
                'active': True,
                'currency_id': gnf[0].id if gnf else False,
                'default_partner_id': customer[0].id if customer else False,
                'iface_available_qty': True,
                'iface_display_categ': True,
                'iface_barcode': True,
                'iface_search': True,
                'receipt_header': 'Thank you for your purchase!',
                'receipt_footer': 'Have a great day!',
                'default_lang': 'en',
            })



