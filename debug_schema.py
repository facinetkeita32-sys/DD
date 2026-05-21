import sqlite3
conn = sqlite3.connect('pos_data.db')
cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND (name LIKE 'pos.%' OR name LIKE 'product.%' OR name LIKE 'res.%') ORDER BY name")
for r in cur:
    print(r[0])
    print()
conn.close()
