import os
import base64
from pathlib import Path

STORAGE_DIR = os.environ.get('IMAGE_STORAGE_PATH') or os.environ.get('RENDER_DISK_PATH') or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'product_images')
PRODUCTS_DIR = os.path.join(STORAGE_DIR, 'products')


def _ensure_dirs():
    Path(PRODUCTS_DIR).mkdir(parents=True, exist_ok=True)


def image_path(product_id):
    return os.path.join(PRODUCTS_DIR, f'{product_id}.jpg')


def save_image(product_id, b64_str):
    if not b64_str:
        return False
    try:
        _ensure_dirs()
        raw = base64.b64decode(b64_str)
        path = image_path(product_id)
        with open(path, 'wb') as f:
            f.write(raw)
        return True
    except Exception:
        return False


def get_image(product_id):
    path = image_path(product_id)
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return f.read()
    return None


def delete_image(product_id):
    path = image_path(product_id)
    if os.path.exists(path):
        os.remove(path)
        return True
    return False
