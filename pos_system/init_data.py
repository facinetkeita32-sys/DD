from .models.res_users import ResUsers
from .models.res_partner import ResPartner
from .models.res_currency import ResCurrency
from .models.res_lang import ResLang
from .models.res_company import ResCompany
from .models.product_product import ProductProduct
from .models.product_category import ProductCategory
from .models.pos_category import PosCategory
from .models.pos_payment_method import PosPaymentMethod
from .models.pos_tax import PosTax
from .models.pos_config import PosConfig
from .models.delivery_zone import DeliveryZone
from .models.stock_lot import StockLot


def load_demo_data():
    ResLang()._init_defaults()
    ResCurrency()._init_defaults()
    ResCompany()._init_defaults()
    ResPartner()._init_defaults()
    ProductCategory()._init_defaults()
    PosCategory()._init_defaults()
    PosTax()._init_defaults()
    PosPaymentMethod()._init_defaults()
    ProductProduct()._init_defaults()
    ResUsers()._init_defaults()
    PosConfig()._init_defaults()
    DeliveryZone()._init_defaults()
    StockLot()._init_defaults()
