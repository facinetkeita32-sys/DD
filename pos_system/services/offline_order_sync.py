"""Read-only central order snapshots and non-destructive local payment merges."""
import math
import uuid
from collections import defaultdict

from ..models.pos_order import PosOrder
from ..models.pos_payment import PosPayment
from ..models.pos_payment_method import PosPaymentMethod
from . import offline_store as store
from .backup_service import _json_value
from .offline_server import SyncError


def server_payment_snapshots(device_id, operation_ids):
    if not isinstance(operation_ids, list) or len(operation_ids) > 100:
        raise SyncError('Invalid order payment request.', 400, 'order_sync_invalid')
    operations = []
    for value in operation_ids:
        try:
            key = str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError) as error:
            raise SyncError('Invalid order payment request.', 400, 'order_sync_invalid') from error
        applied = store.get('applied', key)
        receipt = applied.get('receipt', {}) if applied else {}
        if (not applied or applied.get('device_id') != device_id or receipt.get('id') != key
                or receipt.get('kind') != 'sale' or type(receipt.get('server_id')) is not int):
            raise SyncError('Order is not authorized for this terminal.', 403, 'order_sync_access')
        operations.append((key, receipt['server_id']))
    if len({key for key, _ in operations}) != len(operations):
        raise SyncError('Duplicate order request.', 400, 'order_sync_invalid')
    ids = {server_id for _, server_id in operations}
    orders = {order.id: order for order in PosOrder.browse(list(ids))}
    payments = defaultdict(list)
    for payment in PosPayment.search([]):
        if payment._data.get('order_id') in ids:
            payments[payment._data['order_id']].append({
                'id': payment.id, 'method_id': payment._data.get('payment_method_id'),
                'amount': payment._data.get('amount'),
                'payment_date': _json_value(payment._data.get('payment_date')),
                'reference': payment._data.get('reference') or '',
                'is_change': payment._data.get('is_change') or 0,
            })
    result = []
    for key, server_id in operations:
        order = orders.get(server_id)
        if not order:
            raise SyncError('A synchronized order no longer exists on the server.', 409, 'order_sync_conflict')
        row = order._data
        result.append({'sale_operation_id': key, 'server_id': server_id,
                       'reference': row.get('name'), 'state': row.get('state'),
                       'amount_total': row.get('amount_total'), 'amount_paid': row.get('amount_paid'),
                       'amount_change': row.get('amount_change') or 0,
                       'payments': sorted(payments[server_id], key=lambda payment: payment['id'])})
    return result


def pending_sales():
    """Only query orders already acknowledged and currently pending locally."""
    rows = []
    for key, row in store.all_rows('outbox'):
        if row.get('status') != 'sent' or row.get('operation', {}).get('kind') != 'sale':
            continue
        records = PosOrder.browse(row.get('local_id') or 0)
        if records and records[0].state == 'pending':
            rows.append((key, row))
    return rows


def _number(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise SyncError('Invalid server payment data.', 409, 'order_sync_conflict')
    return value


def _stamp(value):
    return str(value or '').replace('T', ' ')[:19]


def _local_method(server_id):
    if type(server_id) is not int or server_id <= 0:
        raise SyncError('A payment method is missing.', 409, 'order_sync_conflict')
    local_id = store.get('meta', f'catalog-local:pos.payment.method:{server_id}')
    if local_id is None or not PosPaymentMethod.browse(local_id):
        raise SyncError('A payment method could not be mapped to this terminal.', 409, 'order_sync_conflict')
    return local_id


def apply_payment_snapshots(snapshots, requested):
    """Merge only payments, retaining every local order/line and queue record.

    Caller holds the DB lock and transaction, and must re-check the outbox is
    empty after the network request. Any error rolls back the entire merge.
    """
    if not isinstance(snapshots, list) or len(snapshots) != len(requested):
        raise SyncError('Incomplete order payment response.', 409, 'order_sync_conflict')
    expected = dict(requested)
    if {row.get('sale_operation_id') for row in snapshots if isinstance(row, dict)} != set(expected):
        raise SyncError('Mismatched order payment response.', 409, 'order_sync_conflict')
    outbox = store.all_rows('outbox')
    changed = False
    for snapshot in snapshots:
        sale = expected[snapshot['sale_operation_id']]
        records = PosOrder.browse(sale['local_id'])
        if not records or records[0].state != 'pending':
            continue
        order = records[0]
        acknowledged = sale.get('receipt', {})
        if (snapshot.get('server_id') != acknowledged.get('server_id')
                or snapshot.get('reference') != order._data.get('name')):
            raise SyncError('Order identity changed on the server.', 409, 'order_sync_conflict')
        total = _number(snapshot.get('amount_total'))
        paid = _number(snapshot.get('amount_paid'))
        change = _number(snapshot.get('amount_change'))
        if (snapshot.get('state') not in ('pending', 'paid', 'done') or total < 0 or paid < 0
                or abs(total - (order._data.get('amount_total') or 0)) > .000001
                or paid + .000001 < (order._data.get('amount_paid') or 0)):
            raise SyncError('The central order changed and requires review.', 409, 'order_sync_conflict')
        central = snapshot.get('payments')
        if not isinstance(central, list):
            raise SyncError('Invalid server payment data.', 409, 'order_sync_conflict')
        central_by_id = {}
        for payment in central:
            if not isinstance(payment, dict) or type(payment.get('id')) is not int or payment['id'] <= 0:
                raise SyncError('Invalid server payment ID.', 409, 'order_sync_conflict')
            if payment['id'] in central_by_id or _number(payment.get('amount')) < 0:
                raise SyncError('Invalid or duplicate server payment.', 409, 'order_sync_conflict')
            central_by_id[payment['id']] = payment
        if abs(sum(payment['amount'] for payment in central) - paid) > .010001:
            raise SyncError('The central payment history does not match its balance.', 409, 'order_sync_conflict')

        local = {payment.id: payment for payment in PosPayment.search([('order_id', '=', order.id)])}
        claimed_local = set()
        matches = {}
        # Explicit acknowledgements link later payments without guessing by amount.
        for _, row in outbox:
            if row.get('status') != 'sent' or row.get('local_id') != order.id or row.get('operation', {}).get('kind') != 'payment':
                continue
            payment_uuid = row['operation']['data']['uuid']
            local_ids = [pid for pid in local if store.get('meta', f'local:pos.payment:{pid}') == payment_uuid]
            server_id = (row.get('receipt', {}).get('payment') or {}).get('payment_id') or row.get('receipt', {}).get('server_id')
            if len(local_ids) != 1 or server_id not in central_by_id or server_id in matches:
                raise SyncError('A synchronized payment could not be matched.', 409, 'order_sync_conflict')
            matches[server_id] = local_ids[0]
            claimed_local.add(local_ids[0])
        # Initial payments were sent inside the original sale. Match them to
        # saved local rows by exact historical values, one-to-one.
        for original in sale['operation']['data'].get('payments', []):
            pid = original.get('id')
            if pid not in local or pid in claimed_local:
                raise SyncError('An original terminal payment could not be matched.', 409, 'order_sync_conflict')
            possible = [payment for payment in central if payment['id'] not in matches
                        and abs(payment['amount'] - (original.get('amount') or 0)) < .000001
                        and _stamp(payment.get('payment_date')) == _stamp(original.get('payment_date'))
                        and (payment.get('reference') or '') == (original.get('reference') or '')
                        and _local_method(payment['method_id']) == (local[pid]._data.get('payment_method_id') or 0)]
            if not possible:
                raise SyncError('An original terminal payment could not be matched.', 409, 'order_sync_conflict')
            matches[possible[0]['id']] = pid
            claimed_local.add(pid)
        for server_id, payment in central_by_id.items():
            mapping_key = f'order-payment:{snapshot["server_id"]}:{server_id}'
            prior = store.get('meta', mapping_key)
            if prior is not None:
                if (prior not in local or (server_id in matches and matches[server_id] != prior)
                        or (prior in claimed_local and matches.get(server_id) != prior)):
                    raise SyncError('Payment mapping changed on the terminal.', 409, 'order_sync_conflict')
                matches[server_id] = prior
                claimed_local.add(prior)
            elif server_id not in matches:
                imported = PosPayment.create({'order_id': order.id, 'payment_method_id': _local_method(payment['method_id']),
                                              'amount': payment['amount'], 'payment_date': payment.get('payment_date'),
                                              'reference': payment.get('reference') or '',
                                              'is_change': _number(payment.get('is_change') or 0)})
                matches[server_id] = imported.id
                changed = True
            if matches[server_id] in local:
                existing = local[matches[server_id]]._data
                if (abs((existing.get('amount') or 0) - payment['amount']) > .000001
                        or (existing.get('payment_method_id') or 0) != _local_method(payment['method_id'])
                        or _stamp(existing.get('payment_date')) != _stamp(payment.get('payment_date'))
                        or (existing.get('reference') or '') != (payment.get('reference') or '')):
                    raise SyncError('A previously synchronized payment changed on the server.', 409, 'order_sync_conflict')
            store.put('meta', mapping_key, matches[server_id])
        if set(local) - claimed_local:
            raise SyncError('An unacknowledged local payment needs review.', 409, 'order_sync_conflict')
        if (order.state != snapshot['state'] or (order._data.get('amount_paid') or 0) != paid
                or (order._data.get('amount_change') or 0) != change):
            order.write({'state': snapshot['state'], 'amount_paid': paid, 'amount_change': change})
            changed = True
    return changed
