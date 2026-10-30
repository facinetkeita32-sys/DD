"""Bidirectional reference changes, stable local IDs and field-level conflicts."""
import copy
import hashlib
import json
import math

from ..odoo_orm import env, Many2one, Many2many, Boolean, Float, Integer, Date, DateTime
from ..permissions import role_has_permission
from . import offline_store as store
from .offline_server import SyncError, REFERENCE_MODELS, _resource

EDITABLE = {
    'product.product': {
        'name', 'barcode', 'default_code', 'description', 'description_sale', 'list_price',
        'cost_price', 'discount', 'categ_id', 'type', 'available_qty', 'uom_name', 'active',
        'image', 'tax_ids', 'pos_categ_ids', 'track_serial', 'is_favorite', 'color', 'expiration_date',
    },
    'product.category': {'name', 'parent_id', 'description', 'active', 'sequence'},
    'pos.config': {'name', 'currency_id', 'iface_available_qty', 'iface_display_categ',
                   'iface_print_bill', 'iface_search', 'iface_barcode', 'limit_categories',
                   'category_ids', 'default_partner_id', 'payment_method_ids', 'receipt_header',
                   'receipt_footer', 'tax_included', 'default_lang', 'low_stock_threshold'},
    'res.company': {'name', 'logo', 'street', 'city', 'state', 'zip_code', 'country',
                    'phone', 'email', 'website', 'vat', 'receipt_header', 'receipt_footer'},
    'delivery.zone': {'name', 'cost', 'active'},
}

# These are existing application routes, not a second set of editing APIs.
ROUTES = {
    'api.create_product': ('product.product', None),
    'api.update_product': ('product.product', 'product_id'),
    'api.upload_product_image': ('product.product', 'product_id'),
    'api.bulk_update_products': ('product.product', 'ids'),
    'api.create_product_category': ('product.category', None),
    'api.update_product_category': ('product.category', 'cat_id'),
    'api.update_config': ('pos.config', 'config'),
    'api.update_company': ('res.company', 'company'),
    'api.create_delivery_zone': ('delivery.zone', None),
    'api.update_delivery_zone': ('delivery.zone', 'zone_id'),
}


def fields(model):
    return EDITABLE[model] & set(env[model]._fields)


def project(model, record):
    result = {}
    for name in fields(model):
        field = env[model]._fields[name]
        value = record._data.get(name)
        if isinstance(field, Many2many):
            value = sorted(record.read([name])[name])
        elif isinstance(field, Boolean):
            value = bool(value)
        elif isinstance(field, (Float, Integer, Many2one)):
            value = value or 0
        elif isinstance(field, (Date, DateTime)):
            value = str(value) if value else False
        else:
            value = value or ''
        result[name] = value
    return result


def revision(model, record):
    return hashlib.sha256(json.dumps(project(model, record), sort_keys=True).encode()).hexdigest()


def map_id(model, local_id, server_id):
    store.put('meta', f'catalog-server:{model}:{local_id}', server_id)
    store.put('meta', f'catalog-local:{model}:{server_id}', local_id)


def ensure_existing_maps():
    # Upgrade existing paired terminals: their downloaded IDs matched the server
    # before local catalogue creation was supported. Never infer this for new rows.
    for model in REFERENCE_MODELS:
        for record in env[model].search([]):
            if (store.get('meta', f'catalog-server:{model}:{record.id}') is None
                    and not store.get('meta', f'catalog-new:{model}:{record.id}')):
                map_id(model, record.id, record.id)


def reference(model, local_id):
    if not local_id:
        return False
    new_uuid = store.get('meta', f'catalog-new:{model}:{local_id}')
    if new_uuid:
        return {'uuid': new_uuid}
    return {'id': store.get('meta', f'catalog-server:{model}:{local_id}', local_id)}


def encode(model, values):
    encoded = copy.deepcopy(values)
    for name, value in values.items():
        field = env[model]._fields[name]
        if isinstance(field, Many2one):
            encoded[name] = reference(field.comodel_name, value)
        elif isinstance(field, Many2many):
            encoded[name] = [reference(field.comodel_name, item) for item in value]
    return encoded


def resolve(device_id, model, value):
    if not value:
        return False
    if not isinstance(value, dict) or len(value) != 1:
        raise SyncError('Invalid catalogue reference.')
    if 'id' in value:
        key = value['id']
    elif 'uuid' in value:
        mapping = store.get('applied', _resource(device_id, model, value['uuid']))
        if not mapping:
            raise SyncError('A new catalogue record must synchronize before its dependent operations.', 409, 'conflict')
        key = mapping['server_id']
    else:
        raise SyncError('Invalid catalogue reference.')
    if type(key) is not int or key <= 0 or env[model] is None or not env[model].browse(key):
        raise SyncError('A referenced catalogue record no longer exists.', 409, 'conflict')
    return key


def decode(device_id, model, values):
    decoded = copy.deepcopy(values)
    for name, value in values.items():
        field = env[model]._fields[name]
        if isinstance(field, Many2one):
            decoded[name] = resolve(device_id, field.comodel_name, value) or 0
        elif isinstance(field, Many2many):
            if not isinstance(value, list):
                raise SyncError('Invalid catalogue relationship.')
            targets = [resolve(device_id, field.comodel_name, item) for item in value]
            if any(type(item) is not int or item <= 0 for item in targets) or len(set(targets)) != len(targets):
                raise SyncError('Invalid catalogue relationship.')
            decoded[name] = sorted(targets)
    return decoded


def permission(model, creating):
    if model in ('product.product', 'product.category'):
        return 'product.create' if creating else 'product.write'
    return 'settings.write'


def validate_values(model, values):
    if not isinstance(values, dict) or not values or set(values) - fields(model):
        raise SyncError('Unsupported business-settings fields.')
    for name, value in values.items():
        field = env[model]._fields[name]
        if isinstance(field, (Many2one, Many2many)):
            continue
        if isinstance(field, Boolean):
            if type(value) is not bool:
                raise SyncError('Invalid boolean setting.')
        elif isinstance(field, (Float, Integer)):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise SyncError('Invalid numeric setting.')
            if name in ('list_price', 'cost_price', 'available_qty', 'cost', 'low_stock_threshold') and value < 0:
                raise SyncError('Prices, stock quantities and thresholds cannot be negative.')
            if name == 'discount' and not 0 <= value <= 100:
                raise SyncError('Discount must be between zero and 100.')
        elif not isinstance(value, str) and value is not False:
            raise SyncError('Invalid text setting.')
        if isinstance(value, str) and getattr(field, 'size', None) and len(value) > field.size:
            raise SyncError(f'{name} must contain at most {field.size} characters.')
    if 'name' in values and not str(values['name']).strip():
        raise SyncError('A name is required.')
    if 'type' in values and values['type'] not in ('product', 'consu', 'service'):
        raise SyncError('Invalid product type.')


def _conflict(model, values, current, message):
    # Central IDs, not terminal IDs. The client can use this exact base in a new,
    # explicitly approved event; it never mutates an already-submitted event ID.
    encoded = {}
    for name in values:
        field = env[model]._fields[name]
        value = current[name]
        if isinstance(field, Many2one):
            value = {'id': value} if value else False
        elif isinstance(field, Many2many):
            value = [{'id': item} for item in value]
        encoded[name] = value
    raise SyncError(message, 409, 'catalog_conflict', details={'model': model, 'current': encoded})


def apply_change(device_id, payload, user):
    model = payload.get('model')
    if model not in EDITABLE:
        raise SyncError('Unsupported catalogue model.')
    creating = payload.get('action') == 'create'
    if payload.get('action') not in ('create', 'update'):
        raise SyncError('Unsupported catalogue action.')
    if not role_has_permission(user.role, permission(model, creating)):
        raise SyncError('Your role cannot apply this catalogue change.', 403, 'permission')
    if creating and model in ('res.company', 'pos.config'):
        raise SyncError('Company and POS creation require central configuration.', 403)
    raw_values = payload.get('values')
    validate_values(model, raw_values)
    values = decode(device_id, model, raw_values)
    key = _resource(device_id, model, payload['uuid'])
    if creating:
        if store.get('applied', key):
            raise SyncError('Catalogue creation already has a different acknowledgement.', 409, 'conflict')
        if model == 'product.product' and values.get('barcode'):
            if env[model].search([('barcode', '=', values['barcode'])], limit=1):
                raise SyncError('This barcode already exists on the server. Assign a unique barcode and retry.',
                                409, 'catalog_conflict', details={'model': model, 'duplicate_barcode': values['barcode']})
        if model == 'product.category' and env[model].search([('name', '=', values.get('name')),
                                                              ('parent_id', '=', values.get('parent_id') or False)], limit=1):
            raise SyncError('A category with this name already exists on the server.', 409, 'catalog_conflict',
                            details={'model': model, 'duplicate_name': values.get('name')})
        record = env[model].create(values)
        store.put('applied', key, {'server_id': record.id})
    else:
        record_id = resolve(device_id, model, payload.get('record'))
        record = env[model].browse(record_id)[0]
        base = payload.get('base')
        if not isinstance(base, dict) or set(base) != set(values):
            raise SyncError('A comparison base is required for every changed field.')
        baseline = decode(device_id, model, base)
        current = project(model, record)
        for name, value in values.items():
            if name == 'available_qty' and model == 'product.product':
                continue  # Stock edits are movements, never absolute overwrites.
            if current[name] != baseline[name] and current[name] != value:
                _conflict(model, values, current, 'The same fields changed on the server. Review this change before synchronizing.')
        if model == 'product.product' and 'barcode' in values and values['barcode']:
            duplicates = env[model].search([('barcode', '=', values['barcode'])])
            if any(item.id != record.id for item in duplicates):
                _conflict(model, values, current, 'This barcode belongs to another server product.')
        if model == 'product.product' and 'available_qty' in values:
            delta = payload.get('stock_delta')
            if type(delta) not in (int, float) or not math.isfinite(delta):
                raise SyncError('A stock-adjustment delta is required.')
            if abs((values['available_qty'] - baseline['available_qty']) - delta) > .000001:
                raise SyncError('The stock adjustment does not match its base.')
            values['available_qty'] = current['available_qty'] + delta
            if values['available_qty'] < 0:
                _conflict(model, values, current, 'The stock adjustment would produce negative central stock.')
        record.write(values)
    return {'model': model, 'uuid': payload['uuid'], 'server_id': record.id}


def remap_snapshot(snapshot):
    """Retain terminal IDs even when new server/terminal numeric IDs collide."""
    from ..odoo_orm import _db_cache
    models = {name: env[name] for name in REFERENCE_MODELS}
    result = copy.deepcopy(snapshot)
    mappings = {}
    for model in REFERENCE_MODELS:
        occupied = set(_db_cache.get(model, {}).get('_data', {}))
        seq = max(_db_cache.get(model, {}).get('_seq', 0), max(occupied, default=0))
        for row in result['tables'][model]:
            sid = row['id']
            local_id = store.get('meta', f'catalog-local:{model}:{sid}')
            if local_id is None:
                owner = store.get('meta', f'catalog-server:{model}:{sid}')
                reserved = store.get('meta', f'catalog-new:{model}:{sid}')
                if (owner is not None and owner != sid) or reserved:
                    seq += 1
                    while seq in occupied:
                        seq += 1
                    local_id = seq
                else:
                    local_id = sid
                map_id(model, local_id, sid)
            occupied.add(local_id)
            seq = max(seq, local_id)
            mappings[(model, sid)] = local_id
        # Mark which cost fields are actually known; an unprivileged catalogue
        # never turns an unknown cost into a fabricated editable zero.
        if model == 'product.product':
            for row in result['tables'][model]:
                lid = mappings[(model, row['id'])]
                if 'cost_price' in row:
                    store.put('meta', f'catalog-cost-known:{lid}', True)
                elif store.get('meta', f'catalog-cost-known:{lid}'):
                    records = env[model].browse(lid)
                    if records:
                        row['cost_price'] = records[0]._data.get('cost_price')
    for table, rows in result['tables'].items():
        if table in models:
            for row in rows:
                row['id'] = mappings[(table, row['id'])]
                for name, field in models[table]._fields.items():
                    if isinstance(field, Many2one) and field.comodel_name in REFERENCE_MODELS and row.get(name):
                        row[name] = mappings.get((field.comodel_name, row[name]), False)
        else:
            valid = []
            for row in rows:
                converted = {col: mappings.get((col.removesuffix('_id'), value)) for col, value in row.items()}
                if all(converted.values()):
                    valid.append(converted)
            result['tables'][table] = valid
    return result


def conflicts_for(user):
    result = []
    for key, row in store.all_rows('outbox'):
        if row['status'] != 'conflict' or row['operation']['kind'] != 'catalog':
            continue
        payload = row['operation']['data']
        if not role_has_permission(user.role, permission(payload['model'], payload['action'] == 'create')):
            continue
        result.append({'id': key, 'model': payload['model'], 'action': payload['action'],
                       'local_id': row['local_id'], 'values': payload['values'],
                       'current': row.get('conflict', {}).get('current'),
                       'duplicate_barcode': row.get('conflict', {}).get('duplicate_barcode'),
                       'duplicate_name': row.get('conflict', {}).get('duplicate_name')})
    return result


def resolve_conflict(key, decision, overrides, user):
    from .offline_client import enqueue, check_access, config
    check_access(user.id)
    row = store.get('outbox', key)
    if not row or row['status'] != 'conflict' or row['operation']['kind'] != 'catalog':
        raise SyncError('Catalogue conflict not found.', 404)
    payload = copy.deepcopy(row['operation']['data'])
    creating = payload['action'] == 'create'
    if not role_has_permission(user.role, permission(payload['model'], creating)):
        raise SyncError('Your role cannot resolve this change.', 403, 'permission')
    if decision == 'discard':
        if creating:
            raise SyncError('A new product may have dependent sales. Give it a unique name/barcode instead of discarding it.')
    elif decision == 'retry':
        if not isinstance(overrides, dict) or set(overrides) - {'barcode', 'name'}:
            raise SyncError('Only a unique name or barcode may be supplied during review.')
        if any(not isinstance(value, str) or not value.strip() for value in overrides.values()):
            raise SyncError('A non-empty name/barcode is required.')
        if set(overrides) - set(payload['values']):
            raise SyncError('The review cannot introduce unrelated changes.')
        if overrides:
            validate_values(payload['model'], overrides)
        payload['values'].update(overrides)
        current = row.get('conflict', {}).get('current')
        if not creating:
            if not isinstance(current, dict) or set(current) != set(payload['values']):
                raise SyncError('Refresh the conflict before reviewing it.')
            payload['base'] = current
            if 'stock_delta' in payload:
                payload['values']['available_qty'] = current['available_qty'] + payload['stock_delta']
        if overrides:
            records = env[payload['model']].browse(row['local_id'])
            if records:
                records[0].write(overrides)
        enqueue('catalog', payload, row['local_id'], user.id, sequence=row['sequence'])
    else:
        raise SyncError('Choose retry or discard.')
    row['status'] = 'superseded'
    store.put('outbox', key, row)
    settings = config()
    settings['error'] = None
    store.put('meta', 'client', settings)
