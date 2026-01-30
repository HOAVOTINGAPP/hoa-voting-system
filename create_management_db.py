import sqlite3

conn = sqlite3.connect("management/db/management.db")
c = conn.cursor()

c.execute("""
CREATE TABLE IF NOT EXISTS super_admins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    enabled INTEGER DEFAULT 1
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS hoas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    db_path TEXT NOT NULL,
    subscription_start TEXT NOT NULL,
    subscription_end TEXT NOT NULL,
    enabled INTEGER DEFAULT 1
)
""")

c.execute("""
CREATE TABLE IF NOT EXISTS hoa_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    hoa_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    enabled INTEGER DEFAULT 1,
    FOREIGN KEY (hoa_id) REFERENCES hoas(id)
)
""")

conn.commit()
conn.close()

print("Management database created successfully.")
