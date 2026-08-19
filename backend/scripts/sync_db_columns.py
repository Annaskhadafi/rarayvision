import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from backend.app.database.database import engine
from sqlalchemy import text, inspect

insp = inspect(engine)
cols = [c['name'] for c in insp.get_columns('faces')]
print('[*] Existing columns in faces table:', cols)

if 'embedding_v2' not in cols:
    with engine.connect() as conn:
        conn.execute(text('ALTER TABLE faces ADD COLUMN embedding_v2 TEXT;'))
        conn.commit()
        print('[+] Added embedding_v2 column to faces table successfully!')
else:
    print('[✓] Column embedding_v2 already exists.')

insp2 = inspect(engine)
print('[*] Updated columns in faces table:', [c['name'] for c in insp2.get_columns('faces')])
