import json
import time
from datetime import datetime
from functools import wraps
from flask import Blueprint, request, jsonify, g, session, Response

from ..odoo_orm import env, _db_cache as _db, _load_heavy, _batch_load_heavy, HEAVY_COLS, _persist_bulk_delete
from ..models.res_users import ResUsers
from ..models.res_partner import ResPartner
from ..models.res_currency import ResCurrency
from ..models.res_lang import ResLang
from ..models.product_product import ProductProduct
from ..models.product_category import ProductCategory
from ..models.pos_category import PosCategory
from ..models.pos_order import PosOrder
from ..models.pos_order_line import PosOrderLine
from ..models.pos_session import PosSession
from ..models.pos_config import PosConfig
from ..models.pos_payment_method import PosPaymentMethod
from ..models.pos_tax import PosTax
from ..models.pos_payment import PosPayment
from ..models.res_company import ResCompany
from ..models.delivery_zone import DeliveryZone
from ..models.stock_lot import StockLot
from ..models.login_log import LoginLog
from ..models.inventory_item import InventoryItem

api_bp = Blueprint('api', __name__, url_prefix='/api')


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = session.get('user_id')
        if not user_id:
            return jsonify({'error': 'Unauthorized'}), 401
        user = ResUsers().browse(user_id)
        if not user:
            return jsonify({'error': 'User not found'}), 401
        g.user = user[0] if user else None
        g.user_id = user[0].id if user else None
        g.user_role = user[0]._data.get('role', 'cashier') if user else 'cashier'
        return f(*args, **kwargs)
    return decorated


def permission_required(action):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            from ..permissions import role_has_permission
            role = getattr(g, 'user_role', 'cashier')
            if not role_has_permission(role, action):
                return error_response('Forbidden: insufficient permissions', 403)
            return f(*args, **kwargs)
        return decorated
    return decorator


def serialize_model(model_class, records, fields=None):
    result = []
    for rec in records:
        data = rec.read(fields)
        result.append(data)
    return result


def model_to_dict(obj, fields_list=None):
    if isinstance(obj, list):
        return [model_to_dict(o, fields_list) for o in obj if o]
    if not obj:
        return None
    data = {'id': obj.id}
    fnames = fields_list if fields_list else list(obj._fields.keys())
    for fname in fnames:
        field = obj._fields.get(fname)
        val = obj._data.get(fname)
        if (val is None or val == '') and fname in HEAVY_COLS and hasattr(obj, 'id') and obj.id:
            val = _load_heavy(obj.__class__, obj.id, fname)
            if val is not None:
                obj._data[fname] = val
        if isinstance(field, type(None)) and fname == 'id':
            continue
        if isinstance(field, type(None)):
            data[fname] = val
        elif hasattr(field, 'comodel_name') and val:
            rel_name = field.comodel_name
            rel_model = env[rel_name]
            if rel_model:
                rel_rec = rel_model().browse(val)
                if rel_rec:
                    data[fname] = {'id': val, 'name': str(rel_rec[0]._data.get(rel_rec[0]._rec_name, ''))}
                else:
                    data[fname] = {'id': val, 'name': ''}
            else:
                data[fname] = val
        else:
            data[fname] = val
    return data


def error_response(message, status=400):
    return jsonify({'error': message}), status


def success_response(data=None, message=None):
    resp = {'success': True}
    if data is not None:
        resp['data'] = data
    if message:
        resp['message'] = message
    return jsonify(resp)



def log_activity(action, details=''):
    uid = getattr(g, 'user_id', None) or session.get('user_id')
    if uid:
        LoginLog().create({
            'user_id': uid,
            'action': action,
            'details': details,
            'ip_address': request.remote_addr or '',
        })


# === AUTH ===

@api_bp.route('/auth/login', methods=['POST'])
def auth_login():
    data = request.get_json() or {}
    login = data.get('login', '')
    password = data.get('password', '')
    users = ResUsers().search([('login', '=', login), ('password', '=', password)])
    if users:
        now = time.time()
        session['user_id'] = users[0].id
        session['lang'] = users[0].lang
        session['last_activity'] = now
        log_activity('login')
        return success_response(model_to_dict(users[0]))
    return error_response('Invalid credentials', 401)


@api_bp.route('/auth/logout', methods=['POST'])
@login_required
def auth_logout():
    log_activity('logout')
    session.clear()
    return success_response(message='Logged out')


@api_bp.route('/auth/me', methods=['GET'])
@login_required
def auth_me():
    return success_response(model_to_dict(g.user))



# === USERS (admin) ===

@api_bp.route('/users', methods=['GET'])
@login_required
@permission_required('user.read')
def get_users():
    users = ResUsers().search([])
    result = []
    for u in users:
        d = model_to_dict(u)
        d.pop('password', None)
        result.append(d)
    return success_response(result)


@api_bp.route('/users', methods=['POST'])
@login_required
@permission_required('user.create')
def create_user():
    data = request.get_json() or {}
    data.pop('id', None)
    existing = ResUsers().search([('login', '=', data.get('login', ''))])
    if existing:
        return error_response('Login already exists')
    try:
        user = ResUsers().create(data)
        d = model_to_dict(user)
        d.pop('password', None)
        log_activity('create', 'User: %s' % data.get('login', ''))
        return success_response(d, 'User created')
    except Exception as e:
        return error_response(str(e))


@api_bp.route('/users/<int:user_id>', methods=['PUT'])
@login_required
@permission_required('user.write')
def update_user(user_id):
    users = ResUsers().browse([user_id])
    if not users:
        return error_response('User not found', 404)
    data = request.get_json() or {}
    data.pop('id', None)
    data.pop('login', None)
    if data.get('password') == '' or data.get('password') is None:
        data.pop('password', None)
    users[0].write(data)
    d = model_to_dict(users[0])
    d.pop('password', None)
    log_activity('update', 'User ID: %s' % user_id)
    return success_response(d, 'User updated')


@api_bp.route('/users/<int:user_id>', methods=['DELETE'])
@login_required
@permission_required('user.delete')
def delete_user(user_id):
    users = ResUsers().browse([user_id])
    if not users:
        return error_response('User not found', 404)
    if users[0].id == g.user_id:
        return error_response('Cannot delete yourself')
    users[0].unlink()
    log_activity('delete', 'User ID: %s' % user_id)
    return success_response(message='User deleted')


@api_bp.route('/auth/permissions', methods=['GET'])
@login_required
def get_my_permissions():
    from ..permissions import get_role_screens, get_role_actions
    role = g.user_role
    return success_response({
        'role': role,
        'screens': get_role_screens(role),
        'actions': get_role_actions(role),
    })


# === LANGUAGE ===

@api_bp.route('/languages', methods=['GET'])
def get_languages():
    langs = ResLang().search([])
    return success_response(serialize_model(ResLang, langs))


@api_bp.route('/translations/<lang>', methods=['GET'])
def get_translations(lang):
    from ..i18n import translator
    translations = translator.get_translations(lang)
    return success_response(translations)


@api_bp.route('/settings/language', methods=['POST'])
@login_required
def set_language():
    data = request.get_json() or {}
    lang = data.get('lang', 'en')
    session['lang'] = lang
    return success_response(message='Language updated')



# === CURRENCIES ===

@api_bp.route('/currencies', methods=['GET'])
def get_currencies():
    currencies = ResCurrency().search([])
    return success_response(serialize_model(ResCurrency, currencies))



import base64

# === PRODUCTS ===

@api_bp.route('/products', methods=['GET'])
def get_products():
    domain = []
    args = request.args
    if args.get('search'):
        domain.append(('name', 'ilike', args['search']))
    if args.get('category_id'):
        domain.append(('categ_id', '=', int(args['category_id'])))
    if args.get('pos_category_id'):
        domain.append(('pos_categ_ids', 'in', [int(args['pos_category_id'])]))
    products = ProductProduct().search(domain, limit=200)
    fields = [f for f in ProductProduct._fields.keys() if f != 'image']
    result = model_to_dict(products, fields)
    if isinstance(result, list):
        pids = [r['id'] for r in result if r.get('id')]
        if pids:
            images = _batch_load_heavy(ProductProduct, pids, 'image')
            for r in result:
                r['image'] = images.get(r['id'], '') or ''
            all_lots = StockLot().search([('product_id', 'in', pids)])
            expiry_map = {}
            for lot in all_lots:
                pid = lot._data.get('product_id')
                exp = lot._data.get('expiration_date', '') or ''
                if pid and exp:
                    if pid not in expiry_map or exp < expiry_map[pid]:
                        expiry_map[pid] = exp
            for r in result:
                r['nearest_expiry'] = expiry_map.get(r.get('id'), '')
        else:
            for r in result:
                r['image'] = ''
                r['nearest_expiry'] = ''
    resp = success_response(result)
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return resp


@api_bp.route('/products/<int:product_id>', methods=['GET'])
def get_product(product_id):
    products = ProductProduct().browse([product_id])
    if not products:
        return error_response('Product not found', 404)
    return success_response(model_to_dict(products[0]))


@api_bp.route('/products', methods=['POST'])
@login_required
@permission_required('product.create')
def create_product():
    data = request.get_json() or {}
    try:
        product = ProductProduct().create(data)
        log_activity('create', 'Product: %s' % data.get('name', ''))
        return success_response(model_to_dict(product), 'Product created')
    except Exception as e:
        return error_response(str(e))


@api_bp.route('/products/<int:product_id>', methods=['PUT'])
@login_required
@permission_required('product.write')
def update_product(product_id):
    products = ProductProduct().browse([product_id])
    if not products:
        return error_response('Product not found', 404)
    data = request.get_json() or {}
    products[0].write(data)
    log_activity('update', 'Product ID: %s' % product_id)
    fields = [f for f in ProductProduct._fields.keys() if f != 'image']
    return success_response(model_to_dict(products[0], fields), 'Product updated')


@api_bp.route('/products/bulk-update', methods=['POST'])
@login_required
@permission_required('product.write')
def bulk_update_products():
    data = request.get_json() or {}
    ids = data.get('ids', [])
    field = data.get('field')
    value = data.get('value')
    if not ids or not field:
        return error_response('ids and field are required')

    if field == 'available_qty':
        for pid in ids:
            products = ProductProduct().browse([pid])
            if products:
                products[0].write({field: float(value) if value else 0.0})
    else:
        if field == 'categ_id':
            cv = int(value) if value else False
        elif field in ('list_price', 'cost_price'):
            cv = float(value) if value else 0.0
        else:
            cv = value
        ProductProduct.bulk_write(ids, field, cv)

    log_activity('bulk_update', '%s products %s=%s' % (len(ids), field, value))
    updated = ProductProduct().search([('id', 'in', ids)])
    fields = [f for f in ProductProduct._fields.keys() if f != 'image']
    result = model_to_dict(updated, fields)
    return success_response(result, f'{len(ids)} products updated')


@api_bp.route('/products/<int:product_id>', methods=['DELETE'])
@login_required
@permission_required('product.delete')
def delete_product(product_id):
    products = ProductProduct().browse([product_id])
    if not products:
        return error_response('Product not found', 404)
    name = products[0]._data.get('name', product_id)
    products[0].unlink()
    log_activity('delete', 'Product: %s' % name)
    return success_response(message='Product deleted')


@api_bp.route('/products/upload-image', methods=['POST'])
@login_required
@permission_required('product.write')
def upload_product_image():
    product_id = request.args.get('product_id', type=int)
    if not product_id:
        return error_response('product_id is required')
    products = ProductProduct().browse([product_id])
    if not products:
        return error_response('Product not found', 404)
    if 'image' not in request.files:
        return error_response('No image file provided')
    file = request.files['image']
    if not file.filename:
        return error_response('Empty file')
    try:
        img_data = base64.b64encode(file.read()).decode('utf-8')
        products[0].write({'image': img_data})
        return success_response({'id': product_id, 'image': img_data}, 'Image uploaded')
    except Exception as e:
        return error_response(str(e))


@api_bp.route('/products/bulk-import', methods=['POST'])
@login_required
@permission_required('bulk.import')
def bulk_import_products():
    content_type = request.content_type or ''
    results = {'created': 0, 'updated': 0, 'errors': []}

    if 'multipart/form-data' in content_type:
        if 'file' not in request.files:
            return error_response('No file provided')
        file = request.files['file']
        if not file.filename:
            return error_response('Empty file')
        content = file.read().decode('utf-8')
        import csv, io
        reader = csv.DictReader(io.StringIO(content))
        products_data = list(reader)
    else:
        products_data = request.get_json()
        if not isinstance(products_data, list):
            products_data = [products_data]

    field_map = {
        'name': 'name', 'Name': 'name', 'product': 'name',
        'price': 'list_price', 'Price': 'list_price', 'list_price': 'list_price',
        'cost': 'cost_price', 'Cost': 'cost_price', 'cost_price': 'cost_price',
        'qty': 'available_qty', 'Qty': 'available_qty', 'quantity': 'available_qty',
        'barcode': 'barcode', 'Barcode': 'barcode',
        'category': 'categ_id', 'Category': 'categ_id',
        'description': 'description', 'Description': 'description',
        'uom': 'uom_name', 'UOM': 'uom_name', 'unit': 'uom_name',
        'type': 'type', 'Type': 'type',
        'default_code': 'default_code', 'code': 'default_code',
        'active': 'active', 'Active': 'active',
    }

    for row in products_data:
        try:
            vals = {}
            if isinstance(row, dict):
                for k, v in row.items():
                    mapped = field_map.get(k.strip(), k.strip().lower().replace(' ', '_'))
                    vals[mapped] = v.strip() if isinstance(v, str) else v
            else:
                continue

            if not vals.get('name'):
                results['errors'].append(f"Row missing name: {vals}")
                continue

            barcode = vals.get('barcode', '')
            existing = ProductProduct().search([('barcode', '=', barcode)]) if barcode else []
            if existing:
                existing[0].write(vals)
                results['updated'] += 1
            else:
                for num_field in ['list_price', 'cost_price', 'available_qty']:
                    if num_field in vals:
                        try: vals[num_field] = float(vals[num_field])
                        except: vals[num_field] = 0.0
                ProductProduct().create(vals)
                results['created'] += 1
        except Exception as e:
            results['errors'].append(str(e))

    return success_response(results, f"Imported: {results['created']} created, {results['updated']} updated, {len(results['errors'])} errors")



# === LOTS / BATCHES ===

@api_bp.route('/products/<int:product_id>/lots', methods=['GET'])
@login_required
def get_product_lots(product_id):
    import traceback
    try:
        lots = StockLot().search([('product_id', '=', product_id)])
        return success_response(model_to_dict(lots))
    except Exception as e:
        traceback.print_exc()
        return error_response('Failed to load lots: %s' % str(e), 500)


@api_bp.route('/products/<int:product_id>/lots', methods=['POST'])
@login_required
@permission_required('product.write')
def create_product_lot(product_id):
    import traceback
    data = request.get_json() or {}
    data['product_id'] = product_id
    try:
        if not data.get('name'):
            from datetime import datetime
            products = ProductProduct().browse([product_id])
            pname = products[0]._data.get('name', 'Product') if products else 'Product'
            data['name'] = '%s-%s' % (pname.replace(' ', ''), datetime.now().strftime('%Y%m%d%H%M%S'))
        lot = StockLot().create(data)
        StockLot._recompute_product_qty(product_id)
        log_activity('create', 'Lot: %s' % lot.name)
        return success_response(model_to_dict(lot), 'Lot created')
    except Exception as e:
        traceback.print_exc()
        return error_response('Failed to create lot: %s' % str(e), 500)


@api_bp.route('/lots/<int:lot_id>', methods=['PUT'])
@login_required
@permission_required('product.write')
def update_lot(lot_id):
    import traceback
    try:
        lots = StockLot().browse([lot_id])
        if not lots:
            return error_response('Lot not found', 404)
        data = request.get_json() or {}
        lots[0].write(data)
        StockLot._recompute_product_qty(lots[0]._data.get('product_id'))
        log_activity('update', 'Lot ID: %s' % lot_id)
        return success_response(model_to_dict(lots[0]), 'Lot updated')
    except Exception as e:
        traceback.print_exc()
        return error_response('Failed to update lot: %s' % str(e), 500)


@api_bp.route('/lots/<int:lot_id>', methods=['DELETE'])
@login_required
@permission_required('product.write')
def delete_lot(lot_id):
    import traceback
    try:
        lots = StockLot().browse([lot_id])
        if not lots:
            return error_response('Lot not found', 404)
        pid = lots[0]._data.get('product_id')
        name = lots[0].name
        lots[0].unlink()
        if pid:
            StockLot._recompute_product_qty(pid)
        log_activity('delete', 'Lot: %s' % name)
        return success_response(message='Lot deleted')
    except Exception as e:
        traceback.print_exc()
        return error_response('Failed to delete lot: %s' % str(e), 500)


# === PRODUCT CATEGORIES ===

@api_bp.route('/product-categories', methods=['GET'])
def get_product_categories():
    cats = ProductCategory().search([])
    return success_response(serialize_model(ProductCategory, cats))


@api_bp.route('/product-categories', methods=['POST'])
@login_required
@permission_required('product.create')
def create_product_category():
    data = request.get_json() or {}
    data.pop('id', None)
    existing = ProductCategory().search([('name', '=', data.get('name', '')), ('parent_id', '=', False)])
    if existing:
        return error_response('Category already exists')
    try:
        cat = ProductCategory().create(data)
        log_activity('create', 'Category: %s' % data.get('name', ''))
        return success_response(model_to_dict(cat), 'Category created')
    except Exception as e:
        return error_response(str(e))


@api_bp.route('/product-categories/<int:cat_id>', methods=['PUT'])
@login_required
@permission_required('product.write')
def update_product_category(cat_id):
    cats = ProductCategory().browse([cat_id])
    if not cats:
        return error_response('Category not found', 404)
    data = request.get_json() or {}
    data.pop('id', None)
    cats[0].write(data)
    log_activity('update', 'Category ID: %s' % cat_id)
    return success_response(model_to_dict(cats[0]), 'Category updated')


@api_bp.route('/product-categories/<int:cat_id>', methods=['DELETE'])
@login_required
@permission_required('product.delete')
def delete_product_category(cat_id):
    cats = ProductCategory().browse([cat_id])
    if not cats:
        return error_response('Category not found', 404)
    name = cats[0].name
    cats[0].unlink()
    log_activity('delete', 'Category: %s' % name)
    return success_response(message='Category deleted')


# === POS CATEGORIES ===

@api_bp.route('/pos-categories', methods=['GET'])
def get_pos_categories():
    cats = PosCategory().search([])
    return success_response(serialize_model(PosCategory, cats))



# === CUSTOMERS ===

@api_bp.route('/customers', methods=['GET'])
def get_customers():
    domain = [('customer', '=', True)]
    args = request.args
    if args.get('search'):
        domain.append(('name', 'ilike', args['search']))
    customers = ResPartner().search(domain, limit=100)
    orders = PosOrder().search([])
    spent = {}
    due = {}
    for order in orders:
        pid = order._data.get('partner_id', 0) or 0
        if pid:
            amt = float(order._data.get('amount_total', 0) or 0)
            spent[pid] = spent.get(pid, 0) + amt
            if order._data.get('state') == 'pending':
                due[pid] = due.get(pid, 0) + amt
    result = serialize_model(ResPartner, customers)
    for c in result:
        c['total_spent'] = round(spent.get(c['id'], 0), 2)
        c['total_due'] = round(due.get(c['id'], 0), 2)
    return success_response(result)


@api_bp.route('/customers', methods=['POST'])
@login_required
@permission_required('customer.create')
def create_customer():
    data = request.get_json() or {}
    data['customer'] = True
    try:
        partner = ResPartner().create(data)
        log_activity('create', 'Customer: %s' % data.get('name', ''))
        return success_response(model_to_dict(partner), 'Customer created')
    except Exception as e:
        return error_response(str(e))


@api_bp.route('/customers/<int:customer_id>', methods=['PUT'])
@login_required
@permission_required('customer.write')
def update_customer(customer_id):
    partners = ResPartner().browse([customer_id])
    if not partners:
        return error_response('Customer not found', 404)
    data = request.get_json() or {}
    partners[0].write(data)
    log_activity('update', 'Customer ID: %s' % customer_id)
    return success_response(model_to_dict(partners[0]), 'Customer updated')


@api_bp.route('/customers/<int:customer_id>', methods=['GET'])
def get_customer(customer_id):
    partners = ResPartner().browse([customer_id])
    if not partners:
        return error_response('Customer not found', 404)
    return success_response(model_to_dict(partners[0]))



# === ORDERS ===

@api_bp.route('/orders', methods=['GET'])
def get_orders():
    try:
        domain = []
        args = request.args
        if args.get('session_id'):
            domain.append(('session_id', '=', int(args['session_id'])))
        if args.get('status'):
            domain.append(('state', '=', args['status']))
        orders = PosOrder().search(domain, order='id desc', limit=100)
        result = []
        for order in orders:
            d = model_to_dict(order)
            lines_data = []
            lines = PosOrderLine().search([('order_id', '=', order.id)])
            for line in lines:
                ld = model_to_dict(line)
                pid = line._data.get('product_id', 0) or 0
                if pid:
                    product = ProductProduct().browse([pid])
                    if product:
                        ld['product_name'] = product[0]._data.get('name', '')
                lines_data.append(ld)
            d['lines'] = lines_data
            payments_data = []
            payments = PosPayment().search([('order_id', '=', order.id)])
            for pmt in payments:
                pd_data = model_to_dict(pmt)
                pmid = pmt._data.get('payment_method_id', 0) or 0
                if pmid:
                    method = PosPaymentMethod().browse([pmid])
                    if method:
                        pd_data['payment_method_name'] = method[0]._data.get('name', '')
                payments_data.append(pd_data)
            d['payments'] = payments_data
            pid = order._data.get('partner_id', 0) or 0
            if pid:
                partner = ResPartner().browse([pid])
                if partner:
                    d['partner_name'] = partner[0]._data.get('name', '')
            uid = order._data.get('user_id', 0) or 0
            if uid:
                user = ResUsers().browse([uid])
                if user:
                    d['user_name'] = user[0]._data.get('name', '')
            result.append(d)
        return success_response(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return error_response(str(e))


@api_bp.route('/orders/<int:order_id>', methods=['GET'])
def get_order(order_id):
    orders = PosOrder().browse([order_id])
    if not orders:
        return error_response('Order not found', 404)
    order = orders[0]
    d = model_to_dict(order)
    lines = PosOrderLine().search([('order_id', '=', order.id)])
    d['lines'] = []
    for line in lines:
        ld = model_to_dict(line)
        pid = line._data.get('product_id', 0) or 0
        if pid:
            product = ProductProduct().browse([pid])
            if product:
                ld['product_name'] = product[0]._data.get('name', '')
        d['lines'].append(ld)
    payments = PosPayment().search([('order_id', '=', order.id)])
    d['payments'] = [model_to_dict(p) for p in payments]
    pid = order._data.get('partner_id', 0) or 0
    if pid:
        partner = ResPartner().browse([pid])
        if partner:
            d['partner_name'] = partner[0]._data.get('name', '')
    dzid = order._data.get('delivery_zone_id', 0) or 0
    if dzid:
        zone = DeliveryZone().browse([dzid])
        if zone:
            d['delivery_zone_name'] = zone[0]._data.get('name', '')
    return success_response(d)


@api_bp.route('/orders', methods=['POST'])
@login_required
def create_order():
    data = request.get_json() or {}
    lines_data = data.pop('lines', [])
    payments_data = data.pop('payments', [])
    data['user_id'] = g.user_id
    data['name'] = f"ORD-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{g.user_id}"
    session_id = session.get('session_id')
    if session_id:
        data['session_id'] = session_id
    try:
        # Server-side stock validation
        for line_data in lines_data:
            prod_id = line_data.get('product_id')
            qty = float(line_data.get('qty', 0) or 0)
            if prod_id and qty:
                products = ProductProduct().browse([prod_id])
                if products:
                    product = products[0]
                    current_qty = product._data.get('available_qty', 0) or 0
                    if current_qty < qty:
                        return error_response(
                            f"Insufficient stock for '{product.name}': "
                            f"requested {qty}, only {current_qty} available"
                        )

        order_state = data.pop('state', 'paid')
        order = PosOrder().create(data)
        total = 0
        for line_data in lines_data:
            line_data['order_id'] = order.id
            line = PosOrderLine().create(line_data)
            line_total = line.qty * line.price_unit
            disc = line_total * (line.discount / 100)
            subtotal = line_total - disc
            line.write({'price_subtotal': subtotal})
            total += subtotal

            prod_id = line._data.get('product_id') or getattr(line.product_id, 'id', None)
            qty = line._data.get('qty', 0) or 0
            if prod_id and qty:
                StockLot.deduct_fefo(prod_id, qty)

        delivery_cost = float(data.get('delivery_cost', 0) or 0)
        grand_total = total + delivery_cost

        paid_total = 0
        for pmt_data in payments_data:
            pmt_data['order_id'] = order.id
            pmt = PosPayment().create(pmt_data)
            paid_total += pmt.amount

        if order_state == 'pending':
            order.write({
                'amount_total': grand_total,
                'delivery_cost': delivery_cost,
                'amount_paid': 0,
                'amount_change': 0,
                'state': 'pending',
            })
        else:
            order.write({
                'amount_total': grand_total,
                'delivery_cost': delivery_cost,
                'amount_paid': paid_total,
                'amount_change': max(0, paid_total - grand_total),
                'state': 'paid',
            })
        log_activity('create', 'Order: %s' % order.name)
        return success_response(model_to_dict(order), 'Order created')
    except Exception as e:
        return error_response(str(e))


@api_bp.route('/orders/<int:order_id>/validate-payment', methods=['POST'])
@login_required
@permission_required('order.write')
def validate_payment(order_id):
    orders = PosOrder().browse([order_id])
    if not orders:
        return error_response('Order not found', 404)
    order = orders[0]
    if order.state != 'pending':
        return error_response('Order is not pending payment', 400)
    data = request.get_json() or {}
    payment_method_id = data.get('payment_method_id')
    amount = float(data.get('amount', order.amount_total) or 0)
    if payment_method_id:
        PosPayment().create({
            'order_id': order.id,
            'payment_method_id': payment_method_id,
            'amount': amount,
        })
    order.write({
        'amount_paid': order.amount_paid + amount,
        'amount_change': max(0, order.amount_paid + amount - order.amount_total),
        'state': 'paid',
    })
    log_activity('validate_payment', 'Order: %s' % order.name)
    return success_response(model_to_dict(order), 'Payment validated')


@api_bp.route('/orders/<int:order_id>/cancel', methods=['POST'])
@login_required
@permission_required('order.cancel')
def cancel_order(order_id):
    orders = PosOrder().browse([order_id])
    if not orders:
        return error_response('Order not found', 404)
    order = orders[0]
    if order.state in ('cancelled',):
        return error_response('Order is already cancelled')
    lines = PosOrderLine().search([('order_id', '=', order.id)])
    for line in lines:
        prod_id = line._data.get('product_id') or getattr(line.product_id, 'id', None)
        qty = line._data.get('qty', 0) or 0
        if prod_id and qty:
            StockLot.restore_qty(prod_id, qty)
    orders[0].action_cancel()
    log_activity('cancel', 'Order: %s' % order.name)
    return success_response(message='Order cancelled')



# === RECEIPTS ===

@api_bp.route('/receipt/<int:order_id>/html', methods=['GET'])
def get_receipt_html(order_id):
    from ..services.receipt_service import generate_receipt_html
    lang = request.args.get('lang') or session.get('lang', 'en')
    if lang not in ('en', 'fr'):
        lang = 'en'
    html = generate_receipt_html(order_id, lang=lang)
    if html is None:
        return error_response('Order not found', 404)
    return Response(html, mimetype='text/html')


@api_bp.route('/receipt/<int:order_id>/pdf', methods=['GET'])
def get_receipt_pdf(order_id):
    from ..services.receipt_service import generate_receipt_pdf
    lang = request.args.get('lang') or session.get('lang', 'en')
    if lang not in ('en', 'fr'):
        lang = 'en'
    pdf_bytes = generate_receipt_pdf(order_id, lang=lang)
    if pdf_bytes is None:
        return error_response('Order not found', 404)

    orders = PosOrder().browse([order_id])
    ref = orders[0]._data.get('name', '') or f"order_{order_id}" if orders else f"order_{order_id}"

    return Response(
        pdf_bytes,
        mimetype='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename=receipt_{ref}.pdf',
            'Content-Type': 'application/pdf',
        },
    )



# === SESSIONS ===

@api_bp.route('/sessions', methods=['GET'])
def get_sessions():
    sessions = PosSession().search([], order='id desc')
    result = []
    for s in sessions:
        d = model_to_dict(s)
        if s.user_id:
            user = ResUsers().browse([s.user_id])
            d['user_name'] = user[0]._data.get('name', '') if user else ''
        result.append(d)
    return success_response(result)


@api_bp.route('/sessions/current', methods=['GET'])
@login_required
def get_current_session():
    sessions = PosSession().search([('user_id', '=', g.user_id), ('state', 'in', ['opening_control', 'opened'])], limit=1)
    if sessions:
        return success_response(model_to_dict(sessions[0]))
    return success_response(None)


@api_bp.route('/sessions', methods=['POST'])
@login_required
def create_session():
    data = request.get_json() or {}
    data['user_id'] = g.user_id
    data['name'] = f"SES-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    data['state'] = 'opening_control'
    try:
        pos_session = PosSession().create(data)
        session['session_id'] = pos_session.id
        return success_response(model_to_dict(pos_session), 'Session created')
    except Exception as e:
        return error_response(str(e))


@api_bp.route('/sessions/<int:session_id>/open', methods=['POST'])
@login_required
def open_session(session_id):
    sessions = PosSession().browse([session_id])
    if not sessions:
        return error_response('Session not found', 404)
    sessions[0].action_open()
    session['session_id'] = session_id
    return success_response(message='Session opened')


@api_bp.route('/sessions/<int:session_id>/close', methods=['POST'])
@login_required
def close_session(session_id):
    sessions = PosSession().browse([session_id])
    if not sessions:
        return error_response('Session not found', 404)
    data = request.get_json() or {}
    if 'cash_register_balance_end' in data:
        sessions[0].write({'cash_register_balance_end': data['cash_register_balance_end']})
    sessions[0].action_close()
    session.pop('session_id', None)
    return success_response(model_to_dict(sessions[0]), 'Session closed')



# === PAYMENT METHODS ===

@api_bp.route('/payment-methods', methods=['GET'])
def get_payment_methods():
    methods = PosPaymentMethod().search([('active', '=', True)])
    return success_response(serialize_model(PosPaymentMethod, methods))



# === TAXES ===

@api_bp.route('/taxes', methods=['GET'])
def get_taxes():
    taxes = PosTax().search([('active', '=', True)])
    return success_response(serialize_model(PosTax, taxes))



# === CONFIG ===

@api_bp.route('/config', methods=['GET'])
def get_config():
    configs = PosConfig().search([('active', '=', True)], limit=1)
    if configs:
        d = model_to_dict(configs[0])
        raw_currency_id = configs[0]._data.get('currency_id')
        if raw_currency_id:
            cur = ResCurrency().browse([raw_currency_id])
            if cur:
                d['currency'] = model_to_dict(cur[0])
        return success_response(d)
    return success_response(None)


@api_bp.route('/config', methods=['PUT'])
@login_required
@permission_required('settings.write')
def update_config():
    configs = PosConfig().search([('active', '=', True)], limit=1)
    data = request.get_json() or {}
    data.pop('id', None)
    data.pop('currency', None)
    if configs:
        configs[0].write(data)
        d = model_to_dict(configs[0])
        raw_currency_id = configs[0]._data.get('currency_id')
        if raw_currency_id:
            cur = ResCurrency().browse([raw_currency_id])
            if cur:
                d['currency'] = model_to_dict(cur[0])
        return success_response(d, 'Config updated')
    return error_response('No config found', 404)



# === DELIVERY ZONES ===

@api_bp.route('/delivery-zones', methods=['GET'])
def get_delivery_zones():
    zones = DeliveryZone().search([('active', '=', True)])
    return success_response(serialize_model(DeliveryZone, zones))


@api_bp.route('/delivery-zones', methods=['POST'])
@login_required
@permission_required('settings.write')
def create_delivery_zone():
    data = request.get_json() or {}
    data.pop('id', None)
    try:
        zone = DeliveryZone().create(data)
        return success_response(model_to_dict(zone), 'Delivery zone created')
    except Exception as e:
        return error_response(str(e))


@api_bp.route('/delivery-zones/<int:zone_id>', methods=['PUT'])
@login_required
@permission_required('settings.write')
def update_delivery_zone(zone_id):
    zones = DeliveryZone().browse([zone_id])
    if not zones:
        return error_response('Delivery zone not found', 404)
    data = request.get_json() or {}
    data.pop('id', None)
    zones[0].write(data)
    return success_response(model_to_dict(zones[0]), 'Delivery zone updated')


@api_bp.route('/delivery-zones/<int:zone_id>', methods=['DELETE'])
@login_required
@permission_required('settings.write')
def delete_delivery_zone(zone_id):
    zones = DeliveryZone().browse([zone_id])
    if not zones:
        return error_response('Delivery zone not found', 404)
    zones[0].unlink()
    return success_response(message='Delivery zone deleted')



# === DASHBOARD ===

@api_bp.route('/dashboard', methods=['GET'])
@login_required
def get_dashboard():
    today = datetime.now().strftime('%Y-%m-%d')
    today_orders = PosOrder().search([('date_order', 'like', today)])
    total_sales = sum(o.amount_total for o in today_orders)
    total_orders = len(today_orders)

    open_session = PosSession().search([
        ('state', 'in', ['opening_control', 'opened']),
        ('user_id', '=', g.user_id),
    ], limit=1)

    products = ProductProduct().search([('active', '=', True)])
    inventory_value = 0
    for p in products:
        qty = p._data.get('available_qty', 0) or 0
        cost = p._data.get('cost_price', 0) or 0
        price = p._data.get('list_price', 0) or 0
        unit_val = cost if cost > 0 else price
        inventory_value += qty * unit_val

    return success_response({
        'today_sales': total_sales,
        'today_orders': total_orders,
        'total_products': len(products),
        'total_customers': len(ResPartner().search([('customer', '=', True)])),
        'inventory_value': inventory_value,
        'session_status': open_session[0].state if open_session else 'closed',
        'session': model_to_dict(open_session[0]) if open_session else None,
    })



# === REPORTS ===

@api_bp.route('/reports/sales/export', methods=['GET'])
@login_required
@permission_required('report.read')
def export_sales_report_csv():
    period = request.args.get('period', 'daily')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    fmt = request.args.get('format', 'csv')
    now = datetime.now()

    if date_from or date_to:
        all_orders = PosOrder().search([('state', 'in', ['paid', 'done'])])
        orders = []
        for o in all_orders:
            d = o._data.get('date_order', '')[:10]
            if date_from and d < date_from:
                continue
            if date_to and d > date_to:
                continue
            orders.append(o)
    elif period == 'daily':
        date_str = now.strftime('%Y-%m-%d')
        orders = PosOrder().search([('date_order', 'like', date_str), ('state', 'in', ['paid', 'done'])])
    elif period == 'weekly':
        from datetime import timedelta
        week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')
        all_orders = PosOrder().search([('state', 'in', ['paid', 'done'])])
        orders = [o for o in all_orders if o._data.get('date_order', '')[:10] >= week_ago]
    elif period == 'biweekly':
        from datetime import timedelta
        two_weeks_ago = (now - timedelta(days=14)).strftime('%Y-%m-%d')
        all_orders = PosOrder().search([('state', 'in', ['paid', 'done'])])
        orders = [o for o in all_orders if o._data.get('date_order', '')[:10] >= two_weeks_ago]
    elif period == 'monthly':
        month_str = now.strftime('%Y-%m')
        orders = PosOrder().search([('date_order', 'like', month_str), ('state', 'in', ['paid', 'done'])])
    elif period == 'annual':
        year_str = now.strftime('%Y')
        orders = PosOrder().search([('date_order', 'like', year_str), ('state', 'in', ['paid', 'done'])])
    else:
        orders = PosOrder().search([('state', 'in', ['paid', 'done'])])

    total_sales = sum(o.amount_total for o in orders)
    avg_order = total_sales / len(orders) if orders else 0

    import csv, io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Period', period.upper()])
    writer.writerow(['Total Sales', f'{total_sales:.2f}'])
    writer.writerow(['Total Orders', len(orders)])
    writer.writerow(['Avg Order', f'{avg_order:.2f}'])
    writer.writerow([])
    writer.writerow(['Order Ref', 'Date', 'Customer', 'Cashier', 'Items', 'Total', 'Status'])
    for o in orders:
        d = o._data
        olines = PosOrderLine().search([('order_id', '=', o.id)])
        items = []
        for line in olines:
            pid = line._data.get('product_id', 0) or 0
            pname = 'Product'
            if pid:
                p = ProductProduct().browse([pid])
                if p:
                    pname = p[0]._data.get('name', 'Product')
            items.append(f"{pname} x{line.qty}")
        writer.writerow([
            d.get('name', '') or f"Order #{o.id}",
            (d.get('date_order', '') or '')[:19],
            d.get('partner_name', '') or '-',
            d.get('user_name', '') or '',
            ', '.join(items),
            f'{o.amount_total:.2f}',
            d.get('state', ''),
        ])

    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename=sales_report_{period}_{now.strftime("%Y%m%d")}.csv'},
    )


@api_bp.route('/reports/sales', methods=['GET'])
@login_required
def get_sales_report():
    period = request.args.get('period', 'daily')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    now = datetime.now()

    if date_from or date_to:
        all_orders = PosOrder().search([('state', 'in', ['paid', 'done'])])
        orders = []
        for o in all_orders:
            d = o._data.get('date_order', '')[:10]
            if date_from and d < date_from:
                continue
            if date_to and d > date_to:
                continue
            orders.append(o)
    elif period == 'daily':
        date_str = now.strftime('%Y-%m-%d')
        orders = PosOrder().search([('date_order', 'like', date_str), ('state', 'in', ['paid', 'done'])])
    elif period == 'weekly':
        from datetime import timedelta
        week_ago = (now - timedelta(days=7)).strftime('%Y-%m-%d')
        all_orders = PosOrder().search([('state', 'in', ['paid', 'done'])])
        orders = [o for o in all_orders if o._data.get('date_order', '')[:10] >= week_ago]
    elif period == 'biweekly':
        from datetime import timedelta
        two_weeks_ago = (now - timedelta(days=14)).strftime('%Y-%m-%d')
        all_orders = PosOrder().search([('state', 'in', ['paid', 'done'])])
        orders = [o for o in all_orders if o._data.get('date_order', '')[:10] >= two_weeks_ago]
    elif period == 'monthly':
        month_str = now.strftime('%Y-%m')
        orders = PosOrder().search([('date_order', 'like', month_str), ('state', 'in', ['paid', 'done'])])
    elif period == 'annual':
        year_str = now.strftime('%Y')
        orders = PosOrder().search([('date_order', 'like', year_str), ('state', 'in', ['paid', 'done'])])
    else:
        orders = PosOrder().search([('state', 'in', ['paid', 'done'])])

    total_sales = sum(o.amount_total for o in orders)
    total_orders = len(orders)
    avg_order = total_sales / total_orders if total_orders else 0

    order_list = []
    for o in orders[:50]:
        d = model_to_dict(o)
        lines = PosOrderLine().search([('order_id', '=', o.id)])
        d['lines'] = []
        for line in lines:
            ld = model_to_dict(line)
            pid = line._data.get('product_id', 0) or 0
            if pid:
                product = ProductProduct().browse([pid])
                if product:
                    ld['product_name'] = product[0]._data.get('name', '')
            d['lines'].append(ld)
        pid = o._data.get('partner_id', 0) or 0
        if pid:
            partner = ResPartner().browse([pid])
            if partner:
                d['partner_name'] = partner[0]._data.get('name', '')
        order_list.append(d)

    return success_response({
        'period': period,
        'total_sales': total_sales,
        'total_orders': total_orders,
        'avg_order': round(avg_order, 2),
        'orders': order_list,
    })



# === ACTIVITY LOG ===

@api_bp.route('/activity-log', methods=['GET'])
@login_required
def get_activity_log():
    limit = request.args.get('limit', 50, type=int)
    logs = LoginLog().search([], order='timestamp desc', limit=limit)
    result = []
    for log in logs:
        d = model_to_dict(log)
        uid = log._data.get('user_id', 0) or 0
        if uid:
            user = ResUsers().browse([uid])
            if user:
                d['user_name'] = user[0]._data.get('name', '')
        result.append(d)
    return success_response(result)


# === INVENTORY ===

@api_bp.route('/inventory', methods=['GET'])
@login_required
@permission_required('inventory.export')
def get_inventory():
    args = request.args
    domain = []
    if args.get('search'):
        domain.append(('name', 'ilike', args['search']))
    items = InventoryItem().search(domain, limit=500)
    return success_response(serialize_model(InventoryItem, items))


@api_bp.route('/inventory', methods=['POST'])
@login_required
@permission_required('inventory.create')
def create_inventory():
    data = request.get_json() or {}
    if not data.get('name'):
        return error_response('Name is required')
    item = InventoryItem().create(data)
    log_activity('create', 'Inventory: %s' % item.name)
    return success_response(model_to_dict(item), 'Inventory item created')


@api_bp.route('/inventory/<int:item_id>', methods=['PUT'])
@login_required
@permission_required('inventory.write')
def update_inventory(item_id):
    items = InventoryItem().browse([item_id])
    if not items:
        return error_response('Item not found', 404)
    items[0].write(request.get_json() or {})
    log_activity('update', 'Inventory item ID: %s' % item_id)
    return success_response(model_to_dict(items[0]), 'Inventory item updated')


@api_bp.route('/inventory/<int:item_id>', methods=['DELETE'])
@login_required
@permission_required('inventory.delete')
def delete_inventory(item_id):
    items = InventoryItem().browse([item_id])
    if not items:
        return error_response('Item not found', 404)
    name = items[0].name
    items[0].unlink()
    log_activity('delete', 'Inventory: %s' % name)
    return success_response(message='Deleted')


@api_bp.route('/inventory/import', methods=['POST'])
@login_required
@permission_required('inventory.import')
def import_inventory():
    content_type = request.content_type or ''
    results = {'created': 0, 'updated': 0, 'errors': []}
    if 'multipart/form-data' in content_type:
        if 'file' not in request.files:
            return error_response('No file provided')
        file = request.files['file']
        content = file.read().decode('utf-8-sig')
        import csv, io
        reader = csv.DictReader(io.StringIO(content))
        items_data = list(reader)
    else:
        items_data = request.get_json()
        if not isinstance(items_data, list):
            items_data = [items_data]
    field_map = {
        'name': 'name', 'Name': 'name', 'product': 'name', 'Product': 'name',
        'barcode': 'barcode', 'Barcode': 'barcode',
        'quantity': 'quantity', 'Quantity': 'quantity', 'qty': 'quantity', 'Qty': 'quantity',
        'cost_price': 'cost_price', 'Cost': 'cost_price', 'cost': 'cost_price',
        'selling_price': 'selling_price', 'price': 'selling_price', 'Price': 'selling_price',
        'category': 'category', 'Category': 'category',
        'date': 'date', 'Date': 'date',
        'notes': 'notes', 'Notes': 'notes', 'note': 'notes',
    }
    for row in items_data:
        try:
            vals = {}
            if isinstance(row, dict):
                for k, v in row.items():
                    mapped = field_map.get(k.strip(), k.strip().lower().replace(' ', '_'))
                    vals[mapped] = v.strip() if isinstance(v, str) else v
            else:
                continue
            if not vals.get('name'):
                results['errors'].append(f"Row missing name: {vals}")
                continue
            barcode = vals.get('barcode', '')
            existing = InventoryItem().search([('barcode', '=', barcode)]) if barcode else []
            if existing:
                existing[0].write(vals)
                results['updated'] += 1
            else:
                for num_field in ['quantity', 'cost_price', 'selling_price']:
                    if num_field in vals:
                        try: vals[num_field] = float(vals[num_field])
                        except: vals[num_field] = 0.0
                InventoryItem().create(vals)
                results['created'] += 1
        except Exception as e:
            results['errors'].append(str(e))
    log_activity('import', 'Inventory: %s created, %s updated' % (results['created'], results['updated']))
    return success_response(results, 'Imported: %s created, %s updated, %s errors' % (results['created'], results['updated'], len(results['errors'])))


@api_bp.route('/inventory/bulk-update', methods=['POST'])
@login_required
@permission_required('inventory.write')
def bulk_update_inventory():
    data = request.get_json() or {}
    ids = data.get('ids', [])
    field = data.get('field')
    value = data.get('value')
    if not ids or not field:
        return error_response('ids and field are required')
    count = 0
    for iid in ids:
        items = InventoryItem().browse([iid])
        if items:
            if field == 'date':
                items[0].write({'date': (value or '')[:10]})
            elif field in ('quantity', 'cost_price', 'selling_price'):
                items[0].write({field: float(value) if value else 0.0})
            else:
                items[0].write({field: value})
            count += 1
    log_activity('bulk_update', '%s inventory items %s=%s' % (count, field, value))
    return success_response({'updated': count}, '%s items updated' % count)


@api_bp.route('/inventory/bulk-delete', methods=['POST'])
@login_required
@permission_required('inventory.delete')
def bulk_delete_inventory():
    data = request.get_json() or {}
    ids = data.get('ids', [])
    if not ids:
        return error_response('ids are required')
    _persist_bulk_delete(InventoryItem, ids)
    log_activity('delete', '%s inventory items bulk deleted' % len(ids))
    return success_response({'deleted': len(ids)}, '%s items deleted' % len(ids))


# === COMPANY ===

@api_bp.route('/company', methods=['GET'])
def get_company():
    companies = ResCompany().search([], limit=1)
    if companies:
        return success_response(model_to_dict(companies[0]))
    return success_response(None)


@api_bp.route('/company', methods=['PUT'])
@login_required
@permission_required('settings.write')
def update_company():
    companies = ResCompany().search([], limit=1)
    data = request.get_json() or {}
    if companies:
        companies[0].write(data)
        log_activity('update', 'Company settings')
        return success_response(model_to_dict(companies[0]), 'Company updated')
    else:
        company = ResCompany().create(data)
        log_activity('create', 'Company settings')
        return success_response(model_to_dict(company), 'Company created')



# === DB RESET (dev only) ===

@api_bp.route('/system/init', methods=['POST'])
def init_system():
    for table_name, table_data in _db.items():
        if table_name.startswith('res_') or table_name.startswith('product_') or table_name.startswith('pos_'):
            table_data['_data'].clear()
            table_data['_seq'] = 0

    from ..odoo_orm import DB_ONLY_TABLES, get_conn
    conn = get_conn()
    cur = conn.cursor()
    for tbl in DB_ONLY_TABLES:
        pg_table = tbl.replace('.', '_')
        try:
            cur.execute(f'DELETE FROM {pg_table}')
        except Exception:
            conn.rollback()
        else:
            conn.commit()
    cur.close()

    from ..init_data import load_demo_data
    load_demo_data()
    return success_response(message='System initialized with demo data')
