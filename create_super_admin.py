import sqlite3
from werkzeug.security import generate_password_hash

conn = sqlite3.connect("management/db/management.db")
c = conn.cursor()

username = "admin"
password = "admin123"  # change later

c.execute(
    "INSERT OR IGNORE INTO super_admins (username, password_hash) VALUES (?, ?)",
    (username, generate_password_hash(password))
)

conn.commit()
conn.close()

print("Super admin created: admin / admin123")
