import os
import base64
import requests


SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY', '')
BUCKET_NAME = 'product-images'
BUCKET_PUBLIC = True

_storage_ready = False


def _api_url(path):
    return '{}/storage/v1/{}'.format(SUPABASE_URL.rstrip('/'), path.lstrip('/'))


def _headers():
    return {
        'Authorization': 'Bearer {}'.format(SUPABASE_SERVICE_KEY),
        'Content-Type': 'application/json',
    }


def ensure_bucket():
    global _storage_ready
    if _storage_ready:
        return True
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        print('WARN: SUPABASE_URL or SUPABASE_SERVICE_KEY not set, Storage disabled', flush=True)
        return False
    try:
        resp = requests.get(_api_url('bucket'), headers=_headers())
        buckets = resp.json()
        if not any(b.get('name') == BUCKET_NAME for b in buckets):
            resp = requests.post(
                _api_url('bucket'),
                headers=_headers(),
                json={'name': BUCKET_NAME, 'public': BUCKET_PUBLIC},
            )
            if resp.status_code not in (200, 201):
                print('WARN: failed to create bucket: {}'.format(resp.text), flush=True)
                return False
        _storage_ready = True
        return True
    except Exception as e:
        print('WARN: failed to setup Storage: {}'.format(e), flush=True)
        return False


def upload_image(product_id, base64_data):
    if not ensure_bucket():
        return None
    try:
        raw = base64.b64decode(base64_data)
        path = '{}.png'.format(product_id)
        resp = requests.post(
            _api_url('object/{}/{}'.format(BUCKET_NAME, path)),
            headers={'Authorization': 'Bearer {}'.format(SUPABASE_SERVICE_KEY)},
            data=raw,
        )
        if resp.status_code not in (200, 201):
            print('WARN: failed to upload image: {}'.format(resp.text), flush=True)
            return None
        return get_public_url(product_id)
    except Exception as e:
        print('WARN: upload_image error: {}'.format(e), flush=True)
        return None


def delete_image(product_id):
    if not ensure_bucket():
        return False
    try:
        path = '{}.png'.format(product_id)
        resp = requests.delete(
            _api_url('object/{}'.format(BUCKET_NAME)),
            headers=_headers(),
            json={'prefixes': [path]},
        )
        return resp.status_code in (200, 202)
    except Exception as e:
        print('WARN: delete_image error: {}'.format(e), flush=True)
        return False


def get_public_url(product_id):
    return '{}/storage/v1/object/public/{}/{}.png'.format(
        SUPABASE_URL.rstrip('/'), BUCKET_NAME, product_id
    )
