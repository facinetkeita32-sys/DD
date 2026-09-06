import base64
import io

MAX_SIZE = 800
JPEG_QUALITY = 70


def resize_image_b64(b64_data, max_size=MAX_SIZE, quality=JPEG_QUALITY):
    """Shrink a base64 image to a JPEG thumbnail. Returns resized base64,
    or the original string if decoding/resizing fails."""
    if not b64_data:
        return b64_data
    # Strip data-URI prefix if present
    if ',' in b64_data and b64_data.strip().startswith('data:'):
        b64_data = b64_data.split(',', 1)[1]
    try:
        raw = base64.b64decode(b64_data)
    except Exception:
        return b64_data
    # Skip tiny images (already small enough)
    if len(raw) < 50 * 1024:
        return b64_data
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        img = img.convert('RGB')
        if max(img.size) <= max_size:
            # Still re-encode as JPEG to cut PNG weight
            pass
        img.thumbnail((max_size, max_size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality, optimize=True)
        return base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception:
        return b64_data
