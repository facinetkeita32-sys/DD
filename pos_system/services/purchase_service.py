import time
from datetime import datetime
from ..odoo_orm import get_pool, _db_cache, _write_cache_version, get_conn, put_conn


def _get_next_id(conn, table):
    cur = conn.cursor()
    cur.execute('SELECT id FROM "{}" ORDER BY id DESC LIMIT 1 FOR UPDATE'.format(table))
    row = cur.fetchone()
    cur.close()
    return (row[0] + 1) if row else 1


def _format_po_number(pid):
    return 'PO-{:06d}'.format(pid)


def _format_rcv_number(rid):
    return 'RCV-{:06d}'.format(rid)


def calculate_subtotal(items):
    total = 0.0
    for it in items:
        qty = float(it.get('quantity_ordered', it.get('qty', 0)) or 0)
        cost = float(it.get('unit_cost', it.get('cost', 0)) or 0)
        total += qty * cost
    return total


def create_purchase(data, items, user_id=None):
    """Create purchase with PO-TMP then update to PO-000001. Items: list of dicts."""
    from ..models.purchase_order import PurchaseOrder
    from ..models.purchase_item import PurchaseItem
    from ..models.pending_product import PendingProduct
    from ..models.res_currency import ResCurrency

    # Determine currency default GNF
    currency_id = data.get('currency_id')
    if not currency_id:
        gnf = ResCurrency().search([('iso_code', '=', 'GNF')], limit=1)
        if gnf:
            currency_id = gnf[0].id
            data['currency_id'] = currency_id

    # Create with temporary name
    data = dict(data)
    data['name'] = 'PO-TMP'
    if user_id:
        data['created_by'] = user_id
    # Ensure dates
    if not data.get('purchase_date'):
        data['purchase_date'] = datetime.now().strftime('%Y-%m-%d')
    # Compute totals
    subtotal = calculate_subtotal(items)
    additional_cost = float(data.get('additional_cost', 0) or 0)
    discount = float(data.get('discount', 0) or 0)
    grand_total = subtotal + additional_cost - discount
    data['subtotal'] = subtotal
    data['grand_total'] = grand_total
    if not data.get('status'):
        data['status'] = 'draft'

    order = PurchaseOrder.create(data)
    # Update to formatted number
    formatted = _format_po_number(order.id)
    order.write({'name': formatted})
    # Need to update DB directly because write will handle but we ensure
    # Create items
    for it in items:
        qty = float(it.get('quantity_ordered', it.get('qty', it.get('quantity', 0))) or 0)
        unit_cost = float(it.get('unit_cost', it.get('cost', 0)) or 0)
        selling_price = float(it.get('selling_price', it.get('price', 0)) or 0)
        product_id = it.get('product_id') or it.get('product') or False
        pending_id = False
        product_name = it.get('product_name') or it.get('name') or ''
        sku = it.get('sku') or it.get('default_code') or ''
        barcode = it.get('barcode') or ''

        # If product_id is provided and valid, use it
        if product_id:
            try:
                product_id = int(product_id)
            except:
                product_id = False
        # If no product_id but product_name is new, create pending product
        if not product_id and product_name:
            # Check if pending already exists? create new pending
            pending_vals = {
                'name': product_name,
                'category': it.get('category', ''),
                'sku': sku,
                'barcode': barcode,
                'unit_cost': unit_cost,
                'selling_price': selling_price,
                'quantity': qty,
                'supplier_id': data.get('supplier_id') or False,
                'status': 'pending',
                'active': True,
            }
            pending = PendingProduct.create(pending_vals)
            pending_id = pending.id
            # Ensure product_name is set
            if not product_name:
                product_name = pending.name
        else:
            # For existing product, fill product_name if missing
            if product_id and not product_name:
                from ..models.product_product import ProductProduct
                prod = ProductProduct().browse([product_id])
                if prod:
                    product_name = prod[0]._data.get('name', '')
                    if not sku:
                        sku = prod[0]._data.get('default_code', '')
                    if not barcode:
                        barcode = prod[0]._data.get('barcode', '')

        line_total = qty * unit_cost
        item_vals = {
            'purchase_id': order.id,
            'product_id': product_id,
            'pending_product_id': pending_id,
            'product_name': product_name,
            'sku': sku,
            'barcode': barcode,
            'quantity_ordered': qty,
            'quantity_received': 0,
            'unit_cost': unit_cost,
            'selling_price': selling_price,
            'line_total': line_total,
        }
        PurchaseItem.create(item_vals)

    return order


def update_purchase(purchase_id, data, items=None):
    from ..models.purchase_order import PurchaseOrder
    from ..models.purchase_item import PurchaseItem
    from ..models.pending_product import PendingProduct

    orders = PurchaseOrder().browse([purchase_id])
    if not orders:
        raise ValueError('Purchase not found')
    order = orders[0]
    status = order._data.get('status', 'draft')
    if status not in ('draft', 'ordered'):
        raise ValueError('Only draft or ordered purchases can be edited')

    # Handle status transition draft->ordered
    new_status = data.get('status')
    if new_status and new_status != status:
        if status == 'draft' and new_status == 'ordered':
            data['status'] = 'ordered'
        elif new_status == status:
            pass
        else:
            raise ValueError('Invalid status transition')

    # Update fields
    allowed = ['supplier_id', 'purchase_date', 'expected_date', 'invoice_reference', 'notes', 'additional_cost', 'discount', 'currency_id', 'status']
    vals = {}
    for k in allowed:
        if k in data:
            vals[k] = data[k]

    # If items provided, recompute totals and replace items
    if items is not None:
        # Validate items
        if not items:
            raise ValueError('At least one item required')
        # Remove existing items
        existing = PurchaseItem().search([('purchase_id', '=', purchase_id)])
        for it in existing:
            it.unlink()
        # Create new items (similar to create)
        new_subtotal = calculate_subtotal(items)
        vals['subtotal'] = new_subtotal
        additional_cost = float(vals.get('additional_cost', order._data.get('additional_cost', 0)) or 0)
        if 'additional_cost' not in vals:
            additional_cost = float(order._data.get('additional_cost', 0) or 0)
        discount = float(vals.get('discount', order._data.get('discount', 0)) or 0)
        if 'discount' not in vals:
            discount = float(order._data.get('discount', 0) or 0)
        # Use vals if provided else old
        if 'additional_cost' in data:
            additional_cost = float(data.get('additional_cost', 0) or 0)
        if 'discount' in data:
            discount = float(data.get('discount', 0) or 0)
        vals['grand_total'] = new_subtotal + additional_cost - discount

        # Create items
        for it in items:
            qty = float(it.get('quantity_ordered', it.get('qty', it.get('quantity', 0))) or 0)
            unit_cost = float(it.get('unit_cost', it.get('cost', 0)) or 0)
            selling_price = float(it.get('selling_price', it.get('price', 0)) or 0)
            product_id = it.get('product_id') or it.get('product') or False
            if product_id:
                try:
                    product_id = int(product_id)
                except:
                    product_id = False
            pending_id = it.get('pending_product_id') or False
            product_name = it.get('product_name') or it.get('name') or ''
            sku = it.get('sku') or it.get('default_code') or ''
            barcode = it.get('barcode') or ''

            if not product_id and product_name and not pending_id:
                pending_vals = {
                    'name': product_name,
                    'category': it.get('category', ''),
                    'sku': sku,
                    'barcode': barcode,
                    'unit_cost': unit_cost,
                    'selling_price': selling_price,
                    'quantity': qty,
                    'supplier_id': vals.get('supplier_id', order._data.get('supplier_id')) or False,
                    'status': 'pending',
                    'active': True,
                }
                pending = PendingProduct.create(pending_vals)
                pending_id = pending.id
            elif product_id and not product_name:
                from ..models.product_product import ProductProduct
                prod = ProductProduct().browse([product_id])
                if prod:
                    product_name = prod[0]._data.get('name', '')

            line_total = qty * unit_cost
            item_vals = {
                'purchase_id': purchase_id,
                'product_id': product_id,
                'pending_product_id': pending_id,
                'product_name': product_name,
                'sku': sku,
                'barcode': barcode,
                'quantity_ordered': qty,
                'quantity_received': 0,
                'unit_cost': unit_cost,
                'selling_price': selling_price,
                'line_total': line_total,
            }
            PurchaseItem.create(item_vals)
    else:
        # Recompute grand_total if additional_cost/discount changed
        if 'additional_cost' in vals or 'discount' in vals:
            subtotal = float(order._data.get('subtotal', 0) or 0)
            additional_cost = float(vals.get('additional_cost', order._data.get('additional_cost', 0)) or 0)
            discount = float(vals.get('discount', order._data.get('discount', 0)) or 0)
            vals['grand_total'] = subtotal + additional_cost - discount

    if vals:
        order.write(vals)
    return order


def receive_purchase(purchase_id, receive_lines=None, user_id=None):
    """Atomic reception. receive_lines: list of {purchase_item_id, quantity} or None for full remaining."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        # Lock purchase
        cur.execute('SELECT id, status, name FROM "purchase.order" WHERE id=%s FOR UPDATE', (purchase_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError('Purchase not found')
        status = row[1]
        if status in ('cancelled', 'received'):
            raise ValueError('Purchase already {} cannot receive'.format(status))
        if status not in ('ordered', 'partially_received', 'draft'):
            # Allow draft? spec says ordered then received, but draft should be ordered first
            if status == 'draft':
                raise ValueError('Purchase must be ordered before reception')
        # Fetch items
        cur.execute('SELECT id, product_id, pending_product_id, product_name, sku, barcode, quantity_ordered, quantity_received, unit_cost, selling_price FROM "purchase.item" WHERE purchase_id=%s FOR UPDATE', (purchase_id,))
        items = cur.fetchall()
        if not items:
            raise ValueError('No items to receive')
        # Build map
        item_map = {}
        for r in items:
            item_map[r[0]] = {
                'id': r[0],
                'product_id': r[1],
                'pending_product_id': r[2],
                'product_name': r[3],
                'sku': r[4],
                'barcode': r[5],
                'quantity_ordered': float(r[6] or 0),
                'quantity_received': float(r[7] or 0),
                'unit_cost': float(r[8] or 0),
                'selling_price': float(r[9] or 0),
            }
        # Determine what to receive
        to_receive = {}
        if receive_lines:
            for rl in receive_lines:
                pid = int(rl.get('purchase_item_id') or rl.get('id') or rl.get('item_id') or 0)
                qty = float(rl.get('quantity') or rl.get('quantity_received') or rl.get('qty') or 0)
                if pid not in item_map:
                    raise ValueError('Item {} not found in purchase'.format(pid))
                if qty <= 0:
                    raise ValueError('Quantity must be positive for item {}'.format(pid))
                remaining = item_map[pid]['quantity_ordered'] - item_map[pid]['quantity_received']
                if qty > remaining + 0.0001:
                    raise ValueError('Quantity {} exceeds remaining {} for item {}'.format(qty, remaining, pid))
                to_receive[pid] = qty
        else:
            for pid, it in item_map.items():
                remaining = it['quantity_ordered'] - it['quantity_received']
                if remaining > 0:
                    to_receive[pid] = remaining

        if not to_receive:
            raise ValueError('No remaining quantity to receive')

        # Validate every line first (already done) and prepare product creates
        # Collect pending products to create
        pending_to_create = {}
        for pid, qty in to_receive.items():
            it = item_map[pid]
            if not it['product_id'] and it['pending_product_id']:
                # Will need to create product from pending
                pending_to_create[pid] = it['pending_product_id']
            elif not it['product_id'] and not it['pending_product_id']:
                raise ValueError('Item {} has no product'.format(pid))

        # Now perform writes
        # Create receipt
        cur.execute('SELECT id FROM "purchase.receipt" ORDER BY id DESC LIMIT 1 FOR UPDATE')
        row = cur.fetchone()
        new_receipt_id = (row[0] + 1) if row else 1
        receipt_name = _format_rcv_number(new_receipt_id)
        received_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur.execute('INSERT INTO "purchase.receipt" (id, name, purchase_id, received_at, create_date, write_date, create_uid, write_uid) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)', (new_receipt_id, receipt_name, purchase_id, received_at, received_at, received_at, user_id or 0, user_id or 0))

        # For cache update later
        product_updates = []

        for pid, qty in to_receive.items():
            it = item_map[pid]
            product_id = it['product_id']
            pending_pid = it['pending_product_id']
            unit_cost = it['unit_cost']

            # If pending product, create product
            if not product_id and pending_pid:
                cur.execute('SELECT name, category, sku, barcode, unit_cost, selling_price, quantity, supplier_id FROM "pending.product" WHERE id=%s FOR UPDATE', (pending_pid,))
                prow = cur.fetchone()
                if not prow:
                    raise ValueError('Pending product {} not found'.format(pending_pid))
                pname, pcat, psku, pbarcode, punit, psell, pqty, psupp = prow
                # Create product
                cur.execute('SELECT id FROM "product.product" ORDER BY id DESC LIMIT 1 FOR UPDATE')
                prow2 = cur.fetchone()
                new_prod_id = (prow2[0] + 1) if prow2 else 1
                # Find category id if pcat is int?
                categ_id = None
                if pcat:
                    try:
                        # Try to interpret as category name lookup
                        cur.execute('SELECT id FROM "product.category" WHERE name=%s LIMIT 1', (pcat,))
                        crow = cur.fetchone()
                        if crow:
                            categ_id = crow[0]
                    except Exception:
                        pass
                # Insert product
                now = received_at
                cur.execute('INSERT INTO "product.product" (id, name, barcode, default_code, list_price, cost_price, categ_id, type, available_qty, uom_name, active, create_date, write_date, create_uid, write_uid) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', (
                    new_prod_id, pname, pbarcode or '', psku or '', float(psell or unit_cost or 0), float(punit or unit_cost or 0), categ_id, 'product', 0, 'Unit(s)', 1, now, now, user_id or 0, user_id or 0
                ))
                # Update pending product status
                cur.execute('UPDATE "pending.product" SET status=%s, active=%s, write_date=%s, write_uid=%s WHERE id=%s', ('received', 0, now, user_id or 0, pending_pid))
                # Update purchase.item to link to new product
                cur.execute('UPDATE "purchase.item" SET product_id=%s WHERE id=%s', (new_prod_id, pid))
                product_id = new_prod_id
                # Need to also insert stock lot? will handle below
                # For new product, stock_before =0
                stock_before = 0.0
                cost_before = float(punit or unit_cost or 0)
            else:
                # Existing product: get stock and cost
                cur.execute('SELECT available_qty, cost_price FROM "product.product" WHERE id=%s FOR UPDATE', (product_id,))
                prow = cur.fetchone()
                if not prow:
                    raise ValueError('Product {} not found'.format(product_id))
                stock_before = float(prow[0] or 0)
                cost_before = float(prow[1] or 0)

            # Compute average cost
            qty_recv = float(qty)
            stock_after = stock_before + qty_recv
            if stock_after > 0:
                new_avg = (stock_before * cost_before + qty_recv * unit_cost) / stock_after
            else:
                new_avg = unit_cost

            # Update product stock and cost
            cur.execute('UPDATE "product.product" SET available_qty=%s, cost_price=%s, write_date=%s, write_uid=%s WHERE id=%s', (stock_after, new_avg, received_at, user_id or 0, product_id))

            # Create stock lot for receipt
            cur.execute('SELECT id FROM "stock.lot" ORDER BY id DESC LIMIT 1 FOR UPDATE')
            lrow = cur.fetchone()
            new_lot_id = (lrow[0] + 1) if lrow else 1
            lot_name = 'BATCH-PO-{}-{}-{}'.format(purchase_id, product_id, new_lot_id)
            cur.execute('INSERT INTO "stock.lot" (id, name, product_id, available_qty, active, create_date, write_date, create_uid, write_uid) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)', (new_lot_id, lot_name, product_id, qty_recv, 1, received_at, received_at, user_id or 0, user_id or 0))

            # Create receipt item
            cur.execute('SELECT id FROM "purchase.receipt.item" ORDER BY id DESC LIMIT 1 FOR UPDATE')
            ri_row = cur.fetchone()
            new_ri_id = (ri_row[0] + 1) if ri_row else 1
            cur.execute('INSERT INTO "purchase.receipt.item" (id, receipt_id, purchase_item_id, product_id, quantity_received, unit_cost, stock_before, stock_after, create_date, write_date, create_uid, write_uid) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', (new_ri_id, new_receipt_id, pid, product_id, qty_recv, unit_cost, stock_before, stock_after, received_at, received_at, user_id or 0, user_id or 0))

            # Create inventory transaction
            cur.execute('SELECT id FROM "inventory.transaction" ORDER BY id DESC LIMIT 1 FOR UPDATE')
            tr_row = cur.fetchone()
            new_tr_id = (tr_row[0] + 1) if tr_row else 1
            ref = 'PO-{}-RCV-{}'.format(purchase_id, new_receipt_id)
            cur.execute('INSERT INTO "inventory.transaction" (id, product_id, transaction_type, quantity_change, quantity_before, quantity_after, unit_cost, reference, purchase_id, date, create_date, write_date, create_uid, write_uid) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)', (new_tr_id, product_id, 'PURCHASE_RECEIPT', qty_recv, stock_before, stock_after, unit_cost, ref, purchase_id, received_at, received_at, received_at, user_id or 0, user_id or 0))

            # Update purchase.item quantity_received
            new_qty_recv = it['quantity_received'] + qty_recv
            cur.execute('UPDATE "purchase.item" SET quantity_received=%s, write_date=%s, write_uid=%s WHERE id=%s', (new_qty_recv, received_at, user_id or 0, pid))

            product_updates.append((product_id, stock_after, new_avg))

        # Update purchase status
        cur.execute('SELECT quantity_ordered, quantity_received FROM "purchase.item" WHERE purchase_id=%s', (purchase_id,))
        rows = cur.fetchall()
        total_ordered = sum(float(r[0] or 0) for r in rows)
        total_received = sum(float(r[1] or 0) for r in rows)
        if total_received >= total_ordered - 0.0001:
            new_status = 'received'
        elif total_received > 0:
            new_status = 'partially_received'
        else:
            new_status = 'ordered'

        cur.execute('UPDATE "purchase.order" SET status=%s, write_date=%s, write_uid=%s WHERE id=%s', (new_status, received_at, user_id or 0, purchase_id))

        conn.commit()
        cur.close()
        # Update in-memory cache for products
        try:
            for pid, stock_after, new_avg in product_updates:
                if 'product.product' in _db_cache and pid in _db_cache['product.product']['_data']:
                    _db_cache['product.product']['_data'][pid]['available_qty'] = stock_after
                    _db_cache['product.product']['_data'][pid]['cost_price'] = new_avg
                # Also if new product was created, add to cache
                if 'product.product' in _db_cache and pid not in _db_cache['product.product']['_data']:
                    # Fetch product row to populate cache
                    conn2 = get_pool().getconn()
                    try:
                        cur2 = conn2.cursor()
                        cur2.execute('SELECT name, barcode, default_code, list_price, cost_price, categ_id, available_qty FROM "product.product" WHERE id=%s', (pid,))
                        prow = cur2.fetchone()
                        if prow:
                            _db_cache['product.product']['_data'][pid] = {
                                'name': prow[0],
                                'barcode': prow[1],
                                'default_code': prow[2],
                                'list_price': float(prow[3] or 0),
                                'cost_price': float(prow[4] or 0),
                                'categ_id': prow[5],
                                'available_qty': float(prow[6] or 0),
                                'active': True,
                            }
                            _db_cache['product.product']['_seq'] = max(_db_cache['product.product']['_seq'], pid)
                        cur2.close()
                    finally:
                        get_pool().putconn(conn2)
            _write_cache_version()
        except Exception:
            import traceback
            traceback.print_exc()

        return {'receipt_id': new_receipt_id, 'receipt_name': receipt_name, 'status': new_status}

    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cur.close()
        except Exception:
            pass
        pool.putconn(conn)


def cancel_purchase(purchase_id, user_id=None):
    from ..models.purchase_order import PurchaseOrder
    orders = PurchaseOrder().browse([purchase_id])
    if not orders:
        raise ValueError('Purchase not found')
    order = orders[0]
    status = order._data.get('status')
    if status in ('received', 'cancelled'):
        raise ValueError('Cannot cancel received or already cancelled purchase')
    # If partially_received, maybe not allowed? spec allows cancel for draft/ordered? but we allow unless received/cancelled
    order.write({'status': 'cancelled'})
    return order
