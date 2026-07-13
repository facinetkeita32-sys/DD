import base64
from io import BytesIO
try:
    from PIL import Image
except ImportError:
    Image = None

MAX_DIMENSION = 400

def resize_image_b64(b64_str, max_dim=MAX_DIMENSION):
    if not b64_str or not Image:
        return b64_str
    try:
        raw = base64.b64decode(b64_str)
        img = Image.open(BytesIO(raw))
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        w, h = img.size
        if w <= max_dim and h <= max_dim:
            return b64_str
        ratio = max_dim / max(w, h)
        new_w, new_h = int(w * ratio), int(h * ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, 'JPEG', quality=85)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return b64_str
