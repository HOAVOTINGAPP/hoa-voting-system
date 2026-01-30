import os
import sqlite3

DB_DIR = "hoa_databases"

print("Scanning HOA databases...")

for fname in os.listdir(DB_DIR):
    if not fname.endswith(".db"):
        continue

    path = os.path.join(DB_DIR, fname)
    print("Fixing", fname)

    conn = sqlite3.connect(path)
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS owner_proxies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        primary_erf TEXT NOT NULL,
        proxy_erf TEXT UNIQUE NOT NULL
    );

    CREATE TABLE IF NOT EXISTS developer_proxies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        erf TEXT UNIQUE NOT NULL,
        note TEXT
    );

    CREATE TABLE IF NOT EXISTS developer_settings (
        id INTEGER PRIMARY KEY CHECK(id=1),
        is_active INTEGER DEFAULT 0,
        base_votes INTEGER DEFAULT 0,
        proxy_count INTEGER DEFAULT 0,
        comment TEXT
    );
    """)

    try:
        cur.execute("SELECT note FROM developer_proxies LIMIT 1")
    except:
        print("Adding missing 'note' column to", fname)
        cur.execute("ALTER TABLE developer_proxies ADD COLUMN note TEXT")

    exists = cur.execute("SELECT 1 FROM developer_settings WHERE id=1").fetchone()
    if not exists:
        cur.execute("INSERT INTO developer_settings (id) VALUES (1)")

    conn.commit()
    conn.close()

print("All HOA databases fixed.")
