"""Test-only subprocess host. Never imported by the application."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pos_system.services import offline_client
offline_client.start_worker = lambda: None
from pos_system.main import app
from flask import request, jsonify
from pos_system.models.pos_order import PosOrder
from pos_system.models.pos_session import PosSession
from pos_system.models.pos_payment import PosPayment
from pos_system.models.product_product import ProductProduct
from pos_system.models.pos_payment_method import PosPaymentMethod
from pos_system.models.res_users import ResUsers
from pos_system.services import offline_store as store, backup_service
from pos_system.services import email_service

mode = sys.argv[1]
if mode == 'server':
    ResUsers.create({'name': 'Second cashier', 'login': 'cashier2', 'password': '5678',
                     'role': 'cashier', 'active': True})
    ResUsers.create({'name': 'Manager', 'login': 'manager1', 'password': 'manager123',
                     'role': 'manager', 'active': True})
baseline = backup_service.export_full_backup()
control = {'online': True, 'drop_ack': False, 'drop_kind': '', 'capture_error': False, 'mail_failure': False}
mails = []
real_request = offline_client.request_server
real_capture = offline_client.capture
real_capture_change = offline_client.capture_change


def transport(config, path, body=None, credential=None, timeout=8):
    if not control['online']:
        raise offline_client.NetworkUnavailable('Simulated disconnection')
    result = real_request(config, path, body, credential, timeout=timeout)
    if path == 'push' and (control['drop_ack'] or control['drop_kind'] == body['operation']['kind']):
        control['drop_ack'] = False
        control['drop_kind'] = ''
        raise offline_client.NetworkUnavailable('Acknowledgement lost after commit')
    return result


def capture(*args, **kwargs):
    result = real_capture(*args, **kwargs)
    if control['capture_error']:
        raise RuntimeError('Simulated queue/commit failure')
    return result


offline_client.request_server = transport
offline_client.capture = capture


def capture_change(*args, **kwargs):
    result = real_capture_change(*args, **kwargs)
    if control['capture_error']:
        raise RuntimeError('Simulated catalogue queue failure')
    return result


offline_client.capture_change = capture_change


def fake_mail(to_email, subject, body, pdf_bytes=None, filename='receipt.pdf'):
    if control['mail_failure']:
        return False, 'Simulated SMTP error'
    mails.append({'to': to_email, 'subject': subject, 'body': body,
                  'pdf': bool(pdf_bytes and pdf_bytes.startswith(b'%PDF')), 'filename': filename})
    return True, 'Email sent'


email_service.send_receipt_email = fake_mail


@app.route('/__test', methods=['GET', 'POST'])
def debug():
    if request.headers.get('X-Test-Key') != os.environ['OFFLINE_TEST_KEY']:
        return '', 403
    if request.method == 'POST':
        body = request.get_json()
        control.update({key: body[key] for key in control if key in body})
        if 'stock' in body:
            ProductProduct.browse(body['product_id'])[0].write({'available_qty': body['stock']})
        if 'edit_product' in body:
            ProductProduct.browse(body['product_id'])[0].write(body['edit_product'])
        if 'payment_method_active' in body:
            PosPaymentMethod.browse(body['payment_method_id'])[0].write({'active': body['payment_method_active']})
        if body.get('sync'):
            offline_client.synchronize()
        if body.get('expire'):
            grant = store.get('grants', str(body['expire']))
            grant['expires_at'] = 0
            store.put('grants', str(body['expire']), grant)
        if body.get('restore'):
            result = backup_service.restore_from_data(None, baseline)
            assert result['success'], result
        if body.get('reopen_order'):
            # Test-only simulation of an externally corrected central record.
            order = PosOrder.browse(body['reopen_order'])[0]
            for payment in PosPayment.search([('order_id', '=', order.id)]):
                payment.unlink()
            order.write({'amount_paid': 0, 'amount_change': 0, 'state': 'pending'})
    return jsonify({
        'orders': [dict(row._data, id=row.id) for row in PosOrder.search([])],
        'sessions': [dict(row._data, id=row.id) for row in PosSession.search([])],
        'products': [dict(id=row.id, price=row.list_price, quantity=row.available_qty) for row in ProductProduct.search([])],
        'queue': store.all_rows('outbox'), 'client': offline_client.config(),
        'grants': store.all_rows('grants'),
        'mails': mails,
        'users': [dict(id=row.id, login=row.login, password=row.password) for row in ResUsers.search([])],
        'identity': store.get('meta', 'identity'),
    })


app.run(host='127.0.0.1', port=int(sys.argv[2]), debug=False, use_reloader=False, threaded=True)
