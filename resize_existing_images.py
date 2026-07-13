import sys, os
sys.path.insert(0, os.path.dirname(__file__))
if not os.environ.get('DATABASE_URL'):
    os.environ['DB_PATH'] = os.path.join(os.path.dirname(__file__), 'pos_system', 'pos_data.db')

from pos_system.image_utils import resize_image_b64
from pos_system.image_storage import save_image
from pos_system.db import get_conn, _use_pg

conn = get_conn()
engine = 'PostgreSQL' if _use_pg else 'SQLite'
print(f'Connected to {engine}')
try:
    if _use_pg:
        cur = conn.cursor()
        cur.execute("SELECT id, image FROM \"product.product\" WHERE image IS NOT NULL AND image != ''")
        rows = cur.fetchall()
    else:
        cur = conn.execute('SELECT id, image FROM "product.product" WHERE image IS NOT NULL AND image != \'\'')
        rows = cur.fetchall()
    total = len(rows)
    migrated = 0
    skipped = 0
    for rid, img in rows:
        if not img or len(img) < 100:
            skipped += 1
            continue
        old_len = len(img)
        try:
            new_img = resize_image_b64(img)
            save_image(rid, new_img)
            if _use_pg:
                c = conn.cursor()
                c.execute('UPDATE "product.product" SET "image"=\'\' WHERE id=%s', (rid,))
            else:
                conn.execute('UPDATE "product.product" SET "image"=\'\' WHERE id=?', (rid,))
            migrated += 1
            new_len = len(new_img)
            saved = old_len - new_len
            print(f'  [{migrated}] Product #{rid}: {old_len//1024}KB -> {new_len//1024}KB (saved {saved//1024}KB)')
        except Exception as e:
            print(f'  [ERROR] Product #{rid}: {e}')
    conn.commit()
    print(f'\nDone: {total} products with images, {migrated} migrated to disk, {skipped} skipped (tiny)')
finally:
    conn.close()
