import os
import csv
import sqlite3
import random
import string
from io import StringIO, BytesIO
from flask import Flask, request, redirect, url_for, render_template_string, send_file, flash, session
import qrcode
import hashlib
from datetime import datetime

# ================================
# HOA DATABASE ACCESS LAYER
# ================================

def get_db():
    path = session.get("hoa_db_path")
    if not path:
        raise RuntimeError("No HOA database selected")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
def ensure_schema():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS owners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erf TEXT UNIQUE NOT NULL,
            name TEXT,
            id_number TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erf TEXT UNIQUE NOT NULL,
            proxies INTEGER DEFAULT 0,
            otp TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            is_open INTEGER DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            label TEXT NOT NULL
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER,
            erf TEXT,
            option_id INTEGER,
            weight INTEGER
        );
    """)

    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uniq_vote
        ON votes(topic_id, erf);
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS developer_settings (
            id INTEGER PRIMARY KEY CHECK(id=1),
            is_active INTEGER DEFAULT 0,
            base_votes INTEGER DEFAULT 0,
            proxy_count INTEGER DEFAULT 0,
            comment TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS developer_proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erf TEXT UNIQUE,
            note TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS owner_proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            primary_erf TEXT,
            proxy_erf TEXT UNIQUE
        );
    """)

    cur.execute("INSERT OR IGNORE INTO developer_settings (id) VALUES (1);")

    # --- cryptographic vote ledger ---
    cur.execute("PRAGMA table_info(votes);")
    cols = [c[1] for c in cur.fetchall()]

    try:
        if "prev_hash" not in cols:
            cur.execute("ALTER TABLE votes ADD COLUMN prev_hash TEXT;")

        if "vote_hash" not in cols:
            cur.execute("ALTER TABLE votes ADD COLUMN vote_hash TEXT;")

        if "timestamp" not in cols:
            cur.execute("ALTER TABLE votes ADD COLUMN timestamp TEXT;")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


# ================================
# CRYPTOGRAPHIC VOTE LEDGER
# ================================

def compute_vote_hash(prev_hash, erf, topic_id, option_id, weight, timestamp):
    payload = f"{prev_hash}|{erf}|{topic_id}|{option_id}|{weight}|{timestamp}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

app = Flask(__name__)
app.secret_key = "change_this_secret"  # change for production
DB_NAME = "hoa_meeting.db"
ADMIN_PASSWORD = "hoaadmin"  # change for production

def verify_vote_chain():
    conn = get_db()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT prev_hash, erf, topic_id, option_id, weight, timestamp, vote_hash
        FROM votes
        ORDER BY id ASC
    """).fetchall()

    last_hash = "GENESIS"

    for r in rows:
        expected = compute_vote_hash(
            last_hash,
            r["erf"],
            r["topic_id"],
            r["option_id"],
            r["weight"],
            r["timestamp"]
        )

        if expected != r["vote_hash"]:
            conn.close()
            return False

        last_hash = r["vote_hash"]

    conn.close()
    return True

# =================================================
# AUTHENTICATION LAYER (ADDED)
# =================================================
from flask import session, redirect, url_for

MANAGEMENT_DB = "management/db/management.db"

def get_management_db():
    conn = sqlite3.connect(MANAGEMENT_DB)
    conn.row_factory = sqlite3.Row
    return conn

def require_admin():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("username","").strip()
        password = request.form.get("password","").strip()

        conn = get_management_db()
        user = conn.execute(
            "SELECT hoa_id FROM hoa_users WHERE email=? AND password=? AND enabled=1",
            (email,password)
        ).fetchone()

        if not user:
            return render_template_string("<h3>Invalid credentials</h3>")

        hoa = conn.execute(
            "SELECT db_path FROM hoas WHERE id=? AND enabled=1",
            (user["hoa_id"],)
        ).fetchone()
        conn.close()

        if not hoa:
            return render_template_string("<h3>HOA disabled</h3>")

        session.clear()
        session["admin_logged_in"] = True
        session["hoa_db_path"] = hoa["db_path"]

        ensure_schema()

        return redirect("/admin")

    return render_template_string("""
    <html><body>
    <h2>Admin Login</h2>
    <form method="post">
      <input name="username" placeholder="Email"><br>
      <input type="password" name="password" placeholder="Password"><br>
      <button>Login</button>
    </form>
    </body></html>
    """)

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin/login")


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS owners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erf TEXT UNIQUE NOT NULL,
            name TEXT,
            id_number TEXT
        );
    """)
    # Ensure id_number column exists if upgrading an old DB
    try:
        cur.execute("ALTER TABLE owners ADD COLUMN id_number TEXT;")
    except sqlite3.OperationalError:
        pass



    cur.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erf TEXT UNIQUE NOT NULL,
            proxies INTEGER DEFAULT 0,
            otp TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            is_open INTEGER DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            label TEXT NOT NULL,
            FOREIGN KEY(topic_id) REFERENCES topics(id)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            erf TEXT NOT NULL,
            option_id INTEGER NOT NULL,
            weight INTEGER NOT NULL,
            FOREIGN KEY(topic_id) REFERENCES topics(id),
            FOREIGN KEY(option_id) REFERENCES options(id)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS developer_settings (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            is_active INTEGER DEFAULT 0,
            base_votes INTEGER DEFAULT 0,
            proxy_count INTEGER DEFAULT 0,
            comment TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS developer_proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erf TEXT UNIQUE NOT NULL,
            note TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS owner_proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            primary_erf TEXT NOT NULL,
            proxy_erf TEXT UNIQUE NOT NULL
        );
    """)

    # ensure developer settings row
    existing = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
    if not existing:
        cur.execute(
            "INSERT INTO developer_settings (id, is_active, base_votes, proxy_count, comment) "
            "VALUES (1, 0, 0, 0, '');"
        )

    conn.commit()
    conn.close()


def generate_otp(length=6):
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def compute_grand_total(conn=None):
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    cur = conn.cursor()

    regs_raw = cur.execute("SELECT erf, proxies FROM registrations;").fetchall()

    dev_proxies_rows = cur.execute("SELECT erf FROM developer_proxies;").fetchall()
    dev_proxy_erfs = {row["erf"] for row in dev_proxies_rows}

    owner_proxies_rows = cur.execute("SELECT primary_erf, proxy_erf FROM owner_proxies;").fetchall()
    owner_proxy_map = {row["proxy_erf"]: row["primary_erf"] for row in owner_proxies_rows}
    primary_link_counts = {}
    for row in owner_proxies_rows:
        primary = row["primary_erf"]
        primary_link_counts[primary] = primary_link_counts.get(primary, 0) + 1

    settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
    dev_linked_count_row = cur.execute("SELECT COUNT(*) AS c FROM developer_proxies;").fetchone()
    if settings:
        base_votes = settings["base_votes"] or 0
        proxy_count = settings["proxy_count"] or 0
        dev_linked_count = dev_linked_count_row["c"] if dev_linked_count_row else 0
        dev_total_weight = base_votes + proxy_count + dev_linked_count
        dev_active = settings["is_active"]
    else:
        dev_total_weight = 0
        dev_active = 0

    grand_total = 0
    for r in regs_raw:
        erf = r["erf"]
        proxies = r["proxies"] or 0
        if erf == "DEVELOPER":
            weight = dev_total_weight if dev_active else 0
        else:
            blocked = (erf in dev_proxy_erfs) or (erf in owner_proxy_map)
            if blocked:
                weight = 0
            else:
                linked_count = primary_link_counts.get(erf, 0)
                weight = 1 + proxies + linked_count
        grand_total += weight

    if close_conn:
        conn.close()
    return grand_total


BASE_HEAD_ADMIN = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>HOA AGM Admin</title>
  <style>
    body { font-family: Arial, sans-serif; background:#f3f4f6; margin:0; }
    .shell { max-width: 1100px; margin:0 auto; padding:20px; }
    nav { background:#111827; color:white; padding:10px 14px; margin:-20px -20px 20px; }
    nav a { color:#e5e7eb; margin-right:15px; text-decoration:none; font-size:14px; }
    nav a:hover { text-decoration:underline; color:white; }
    .card { background:white; padding:16px 20px; border-radius:10px; box-shadow:0 4px 12px rgba(0,0,0,0.08); margin-bottom:16px; }
    h1 { margin-top:0; }
    h3 { margin-bottom:4px; }
    table { border-collapse:collapse; width:100%; margin-top:8px; }
    th, td { border:1px solid #e5e7eb; padding:6px 8px; font-size:13px; text-align:left; }
    th { background:#e5e7eb; }
    input[type=text], input[type=number], input[type=password], input[type=file], textarea {
        width:100%; max-width:360px; padding:6px 8px; border-radius:6px; border:1px solid #d1d5db;
        font-family:inherit; font-size:14px;
    }
    button { background:#2563eb; color:white; border:none; border-radius:999px; padding:6px 14px; cursor:pointer; font-size:14px; }
    button:hover { background:#1d4ed8; }
    ul.messages { list-style:none; padding-left:0; }
    ul.messages li { margin-bottom:4px; font-size:13px; }
    .subtle { font-size:12px; color:#6b7280; }
  </style>
</head>
<body>
<div class="shell">
<nav>
  <a href="{{ url_for('admin_dashboard') }}">Dashboard</a>
  <a href="{{ url_for('admin_owners') }}">Owners</a>
  <a href="{{ url_for('admin_owner_proxies') }}">Owner Proxy Allocator</a>
  <a href="{{ url_for('admin_registrations') }}">Registrations</a>
  <a href="{{ url_for('admin_scan_register') }}">Scan ID</a>
  <a href="{{ url_for('admin_topics') }}">Topics & Voting</a>
  <a href="{{ url_for('admin_developer') }}">Developer</a>
  <a href="{{ url_for('admin_export') }}">Export Results</a>
  <a href="{{ url_for('admin_reset') }}">Reset All</a>
  <a href="{{ url_for('admin_logout') }}">Logout</a>
</nav>
{% with messages = get_flashed_messages() %}
  {% if messages %}
    <ul class="messages">
      {% for m in messages %}
        <li>{{ m }}</li>
      {% endfor %}
    </ul>
  {% endif %}
{% endwith %}
"""

BASE_HEAD_PUBLIC = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>HOA AGM Voting</title>
  <style>
    body { font-family: Arial, sans-serif; background:#f3f4f6; margin:0; }
    .shell { max-width: 700px; margin:0 auto; padding:20px; }
    .card { background:white; padding:16px 20px; border-radius:10px; box-shadow:0 4px 12px rgba(0,0,0,0.08); margin-bottom:16px; }
    h1 { margin-top:0; }
    h3 { margin-bottom:4px; }
    table { border-collapse:collapse; width:100%; margin-top:8px; }
    th, td { border:1px solid #e5e7eb; padding:6px 8px; font-size:13px; text-align:left; }
    th { background:#e5e7eb; }
    input[type=text], input[type=password] {
        width:100%; max-width:360px; padding:6px 8px; border-radius:6px; border:1px solid #d1d5db;
        font-family:inherit; font-size:14px;
    }
    button { background:#2563eb; color:white; border:none; border-radius:999px; padding:6px 14px; cursor:pointer; font-size:14px; }
    button:hover { background:#1d4ed8; }
    ul.messages { list-style:none; padding-left:0; }
    ul.messages li { margin-bottom:4px; font-size:13px; }
    .subtle { font-size:12px; color:#6b7280; }
  </style>
</head>
<body>
<div class="shell">
{% with messages = get_flashed_messages() %}
  {% if messages %}
    <ul class="messages">
      {% for m in messages %}
        <li>{{ m }}</li>
      {% endfor %}
    </ul>
  {% endif %}
{% endwith %}
"""


def admin_logged_in():
    return session.get("admin_logged_in", False)


@app.route("/admin")
def admin_dashboard():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    vote_url = url_for("vote_topic_selector", _external=True)
    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>HOA AGM Admin Dashboard</h1>
  <p>Use the navigation above to manage the meeting.</p>
  <p class="subtle">Voting link for owners (and developer): <code>{{ vote_url }}</code></p>
</div>
""" + BASE_TAIL
    return render_template_string(template, vote_url=vote_url)


@app.route("/admin/owners", methods=["GET", "POST"])
def admin_owners():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            flash("Please choose a CSV file.")
            conn.close()
            return redirect(url_for("admin_owners"))
        try:
            stream = StringIO(file.stream.read().decode("utf-8"))
            reader = csv.reader(stream)
            count = 0
            for row in reader:
                if not row:
                    continue
                # Skip header row if it starts with "erf"
                if row[0].strip().lower() == "erf":
                    continue
                erf = row[0].strip().upper()
                name = row[1].strip() if len(row) > 1 else ""
                id_number = row[2].strip() if len(row) > 2 else ""
                if not erf:
                    continue
                cur.execute(
                    """
                    INSERT INTO owners (erf, name, id_number)
                    VALUES (?, ?, ?)
                    ON CONFLICT(erf) DO UPDATE SET
                        name=excluded.name,
                        id_number=excluded.id_number;
                    """,
                    (erf, name, id_number),
                )
                count += 1
            conn.commit()
            flash(f"Owners uploaded/updated: {count}")
        except Exception as e:
            flash(f"Error reading CSV: {e}")
        conn.close()
        return redirect(url_for("admin_owners"))

    owners = cur.execute("SELECT * FROM owners ORDER BY erf;").fetchall()
    conn.close()
    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Owners</h1>
  <h3>Upload Owners CSV</h3>
  <p class="subtle">CSV format: <code>erf,owner_name,id_number</code>. ID number is optional but needed for ID scanning.</p>
  <form method="post" enctype="multipart/form-data">
    <input type="file" name="file" accept=".csv">
    <button type="submit">Upload</button>
  </form>
  <hr>
  <h3>Current Owners</h3>
  <table>
    <tr><th>ERF</th><th>Name</th><th>ID Number</th></tr>
    {% for o in owners %}
      <tr>
        <td>{{ o['erf'] }}</td>
        <td>{{ o['name'] }}</td>
        <td>{{ o['id_number'] or '' }}</td>
      </tr>
    {% endfor %}
  </table>
</div>
""" + BASE_TAIL
    return render_template_string(template, owners=owners)


@app.route("/admin/owner_proxies", methods=["GET", "POST"])
def admin_owner_proxies():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    if request.method == "POST":
        form_type = request.form.get("form_type", "")
        if form_type == "add":
            primary_erf = request.form.get("primary_erf", "").strip().upper()
            proxy_erf = request.form.get("proxy_erf", "").strip().upper()
            if not primary_erf or not proxy_erf:
                flash("Both ERFs are required.")
            elif primary_erf == proxy_erf:
                flash("An ERF cannot be a proxy for itself.")
            else:
                owner_primary = cur.execute("SELECT * FROM owners WHERE erf = ?;", (primary_erf,)).fetchone()
                owner_proxy = cur.execute("SELECT * FROM owners WHERE erf = ?;", (proxy_erf,)).fetchone()
                if not owner_primary and primary_erf != "DEVELOPER":
                    flash(f"No owner for proxy holder ERF {primary_erf}.")
                elif not owner_proxy:
                    flash(f"No owner for ERF to link {proxy_erf}.")
                else:
                    dev_existing = cur.execute("SELECT 1 FROM developer_proxies WHERE erf = ?;", (proxy_erf,)).fetchone()
                    if dev_existing:
                        flash(f"ERF {proxy_erf} is already linked to the developer.")
                    else:
                        try:
                            cur.execute(
                                "INSERT INTO owner_proxies (primary_erf, proxy_erf) VALUES (?, ?);",
                                (primary_erf, proxy_erf),
                            )
                            conn.commit()
                            flash(f"ERF {proxy_erf} now represented by {primary_erf}.")
                        except sqlite3.IntegrityError:
                            flash(f"ERF {proxy_erf} is already linked as a proxy.")
        elif form_type == "delete":
            pid = request.form.get("proxy_id", "").strip()
            try:
                pid_int = int(pid)
                cur.execute("DELETE FROM owner_proxies WHERE id = ?;", (pid_int,))
                conn.commit()
                flash("Owner proxy link removed.")
            except ValueError:
                flash("Invalid proxy ID.")
        conn.close()
        return redirect(url_for("admin_owner_proxies"))

    owner_proxies_rows = cur.execute("""
        SELECT op.id, op.primary_erf, op.proxy_erf, o.name
        FROM owner_proxies op
        LEFT JOIN owners o ON o.erf = op.proxy_erf
        ORDER BY op.primary_erf, op.proxy_erf;
    """).fetchall()
    total_here = compute_grand_total(conn)
    conn.close()
    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Owner Proxy Allocator</h1>
  <p class="subtle">
    Link ERFs so that one owner represents another ERF. Linked ERFs cannot vote individually.
  </p>
  <p class="subtle">Current total vote weight (all ERFs): <strong>{{ total_here }}</strong></p>
  <h3>Add Owner Proxy</h3>
  <form method="post">
    <input type="hidden" name="form_type" value="add">
    <p><label>Proxy holder ERF (voting owner):<br><input type="text" name="primary_erf" required></label></p>
    <p><label>ERF to link (represented ERF):<br><input type="text" name="proxy_erf" required></label></p>
    <button type="submit">Add Owner Proxy</button>
  </form>
  <hr>
  <h3>Current Owner Proxy Links</h3>
  {% if not owner_proxies %}
    <p class="subtle">No owner proxies linked yet.</p>
  {% else %}
    <table>
      <tr><th>Proxy holder ERF</th><th>ERF represented</th><th>Owner Name</th><th>Action</th></tr>
      {% for p in owner_proxies %}
        <tr>
          <td>{{ p['primary_erf'] }}</td>
          <td>{{ p['proxy_erf'] }}</td>
          <td>{{ p['name'] or '' }}</td>
          <td>
            <form method="post" style="display:inline;">
              <input type="hidden" name="form_type" value="delete">
              <input type="hidden" name="proxy_id" value="{{ p['id'] }}">
              <button type="submit">Remove</button>
            </form>
          </td>
        </tr>
      {% endfor %}
    </table>
  {% endif %}
</div>
""" + BASE_TAIL
    return render_template_string(template, owner_proxies=owner_proxies_rows, total_here=total_here)


@app.route("/admin/registrations", methods=["GET", "POST"])
def admin_registrations():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    if request.method == "POST":
        erf = request.form.get("erf", "").strip().upper()
        proxies = request.form.get("proxies", "0").strip()
        if not erf:
            flash("ERF is required.")
            conn.close()
            return redirect(url_for("admin_registrations"))
        try:
            proxies_int = int(proxies)
            if proxies_int < 0:
                proxies_int = 0
        except ValueError:
            proxies_int = 0

        owner = cur.execute("SELECT * FROM owners WHERE erf = ?;", (erf,)).fetchone()
        if not owner and erf != "DEVELOPER":
            flash(f"No owner found for ERF {erf}.")
            conn.close()
            return redirect(url_for("admin_registrations"))

        otp = generate_otp()
        cur.execute(
            "INSERT INTO registrations (erf, proxies, otp) VALUES (?, ?, ?) "
            "ON CONFLICT(erf) DO UPDATE SET proxies=excluded.proxies, otp=excluded.otp;",
            (erf, proxies_int, otp),
        )
        conn.commit()
        flash(f"Registered ERF {erf} with {proxies_int} numeric proxies. OTP: {otp}")
        conn.close()
        return redirect(url_for("admin_registrations"))

    regs_raw = cur.execute("""
        SELECT r.erf, r.proxies, r.otp, o.name
        FROM registrations r
        LEFT JOIN owners o ON o.erf = r.erf
        ORDER BY r.erf;
    """).fetchall()

    dev_proxies_rows = cur.execute("SELECT erf FROM developer_proxies;").fetchall()
    dev_proxy_erfs = {row["erf"] for row in dev_proxies_rows}

    owner_proxies_rows = cur.execute("SELECT primary_erf, proxy_erf FROM owner_proxies;").fetchall()
    owner_proxy_map = {row["proxy_erf"]: row["primary_erf"] for row in owner_proxies_rows}
    primary_link_counts = {}
    for row in owner_proxies_rows:
        primary_link_counts[row["primary_erf"]] = primary_link_counts.get(row["primary_erf"], 0) + 1

    dev_settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
    dev_linked_count_row = cur.execute("SELECT COUNT(*) AS c FROM developer_proxies;").fetchone()
    if dev_settings:
        base_votes = dev_settings["base_votes"] or 0
        proxy_count = dev_settings["proxy_count"] or 0
        dev_linked_count = dev_linked_count_row["c"] if dev_linked_count_row else 0
        dev_total_weight = base_votes + proxy_count + dev_linked_count
        dev_active = dev_settings["is_active"]
    else:
        dev_total_weight = 0
        dev_active = 0

    regs = []
    grand_total_weight = 0
    for r in regs_raw:
        erf = r["erf"]
        proxies = r["proxies"] or 0
        if erf == "DEVELOPER":
            total_weight = dev_total_weight if dev_active else 0
        else:
            blocked = (erf in dev_proxy_erfs) or (erf in owner_proxy_map)
            if blocked:
                total_weight = 0
            else:
                linked_count = primary_link_counts.get(erf, 0)
                total_weight = 1 + proxies + linked_count
        grand_total_weight += total_weight
        regs.append({
            "erf": erf,
            "name": r["name"],
            "proxies": proxies,
            "otp": r["otp"],
            "linked_count": primary_link_counts.get(erf, 0),
            "total_weight": total_weight,
            "is_dev_proxy": erf in dev_proxy_erfs,
        })

    conn.close()
    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Registrations</h1>
  <h3>Register Owner / Update Numeric Proxies</h3>
  <p class="subtle">Place the cursor in the ERF box and scan the owner's ID/ERF (scanner types and presses Enter).</p>
  <form method="post">
    <p><label>ERF:<br><input type="text" name="erf" required autofocus></label></p>
    <p><label>Numeric Proxies:<br><input type="number" name="proxies" min="0" value="0"></label></p>
    <button type="submit">Save</button>
  </form>
  <hr>
  <h3>Registered ERFs</h3>
  <p class="subtle">
    Total vote weight = 1 (own ERF) + numeric proxies + number of linked ERFs via Owner Proxy Allocator.
    ERFs linked to the developer or as owner proxies are blocked from individual voting.
  </p>
  <table>
    <tr>
      <th>ERF</th><th>Owner Name</th><th>Numeric Proxies</th>
      <th>Linked ERFs (owner proxies)</th><th>Total Vote Weight</th><th>OTP</th><th>Developer Proxy?</th>
    </tr>
    {% for r in regs %}
      <tr>
        <td>{{ r['erf'] }}</td>
        <td>{{ r['name'] or '' }}</td>
        <td>{{ r['proxies'] }}</td>
        <td>{{ r['linked_count'] }}</td>
        <td>{{ r['total_weight'] }}</td>
        <td><code>{{ r['otp'] or '' }}</code></td>
        <td>{% if r['is_dev_proxy'] %}Yes{% else %}No{% endif %}</td>
      </tr>
    {% endfor %}
    <tr>
      <td colspan="4"><strong>Total vote weight (all ERFs)</strong></td>
      <td><strong>{{ grand_total_weight }}</strong></td>
      <td colspan="2"></td>
    </tr>
  </table>
</div>
""" + BASE_TAIL
    return render_template_string(
        template,
        regs=regs,
        grand_total_weight=grand_total_weight,
    )


@app.route("/admin/topics", methods=["GET", "POST"])
def admin_topics():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        if not title:
            flash("Topic title is required.")
        else:
            cur.execute(
                "INSERT INTO topics (title, description, is_open) VALUES (?, ?, 0);",
                (title, description),
            )
            conn.commit()
            flash("Topic created.")
        conn.close()
        return redirect(url_for("admin_topics"))

    topics = cur.execute("SELECT * FROM topics ORDER BY id DESC;").fetchall()
    settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
    dev_active = bool(settings["is_active"]) if settings else False
    conn.close()
    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Topics & Voting</h1>
  <h3>Create New Topic</h3>
  <form method="post">
    <p><label>Title:<br><input type="text" name="title" required></label></p>
    <p><label>Description (optional):<br><textarea name="description"></textarea></label></p>
    <button type="submit">Create Topic</button>
  </form>
  <hr>
  <h3>Existing Topics</h3>
  <table>
    <tr><th>ID</th><th>Title</th><th>Open?</th><th>Options</th><th>Developer Vote</th><th>Toggle</th></tr>
    {% for t in topics %}
      <tr>
        <td>{{ t['id'] }}</td>
        <td>{{ t['title'] }}</td>
        <td>{{ 'Yes' if t['is_open'] else 'No' }}</td>
        <td><a href="{{ url_for('admin_topic_options', topic_id=t['id']) }}">Manage Options</a></td>
        <td>
          {% if dev_active %}
            <a href="{{ url_for('admin_developer_vote', topic_id=t['id']) }}">Record Developer Vote (admin)</a>
          {% else %}
            <span class="subtle">Developer disabled</span>
          {% endif %}
        </td>
        <td>
          <a href="{{ url_for('admin_toggle_topic', topic_id=t['id']) }}">
            {% if t['is_open'] %}Close{% else %}Open{% endif %}
          </a>
        </td>
      </tr>
    {% endfor %}
  </table>
  <p class="subtle">Voting link for owners: <code>{{ url_for('vote_topic_selector', _external=True) }}</code></p>
</div>
""" + BASE_TAIL
    return render_template_string(template, topics=topics, dev_active=dev_active)


@app.route("/admin/topic/<int:topic_id>/options", methods=["GET", "POST"])
def admin_topic_options(topic_id):
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    topic = cur.execute("SELECT * FROM topics WHERE id = ?;", (topic_id,)).fetchone()
    if not topic:
        conn.close()
        return "Topic not found", 404
    if request.method == "POST":
        label = request.form.get("label", "").strip()
        if not label:
            flash("Option label required.")
        else:
            cur.execute("INSERT INTO options (topic_id, label) VALUES (?, ?);", (topic_id, label))
            conn.commit()
            flash("Option added.")
        conn.close()
        return redirect(url_for("admin_topic_options", topic_id=topic_id))

    options = cur.execute("SELECT * FROM options WHERE topic_id = ? ORDER BY id;", (topic_id,)).fetchall()
    conn.close()
    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Options for Topic: {{ topic['title'] }}</h1>
  <h3>Add Option</h3>
  <form method="post">
    <p><label>Option label:<br><input type="text" name="label" required></label></p>
    <button type="submit">Add</button>
  </form>
  <hr>
  <h3>Current Options</h3>
  <ul>
    {% for o in options %}
      <li>{{ o['label'] }}</li>
    {% endfor %}
  </ul>
  <p><a href="{{ url_for('admin_topics') }}">Back to Topics</a></p>
</div>
""" + BASE_TAIL
    return render_template_string(template, topic=topic, options=options)


@app.route("/admin/topic/<int:topic_id>/toggle")
def admin_toggle_topic(topic_id):
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    topic = cur.execute("SELECT * FROM topics WHERE id = ?;", (topic_id,)).fetchone()
    if not topic:
        conn.close()
        return "Topic not found", 404
    new_state = 0 if topic["is_open"] else 1
    cur.execute("UPDATE topics SET is_open = ? WHERE id = ?;", (new_state, topic_id))
    conn.commit()
    conn.close()
    flash(f"Topic '{topic['title']}' voting is now {'open' if new_state else 'closed'}.")
    return redirect(url_for("admin_topics"))


@app.route("/admin/developer", methods=["GET", "POST"])
def admin_developer():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    if request.method == "POST":
        form_type = request.form.get("form_type", "")
        if form_type == "settings":
            is_active = 1 if request.form.get("is_active") == "on" else 0
            base_votes = request.form.get("base_votes", "0").strip()
            proxy_count = request.form.get("proxy_count", "0").strip()
            comment = request.form.get("comment", "").strip()
            try:
                base_votes_int = max(0, int(base_votes))
            except ValueError:
                base_votes_int = 0
            try:
                proxy_count_int = max(0, int(proxy_count))
            except ValueError:
                proxy_count_int = 0
            cur.execute(
                "UPDATE developer_settings SET is_active=?, base_votes=?, proxy_count=?, comment=? WHERE id=1;",
                (is_active, base_votes_int, proxy_count_int, comment),
            )
            conn.commit()
            flash("Developer settings updated.")
            if is_active == 1:
                reg_dev = cur.execute("SELECT * FROM registrations WHERE erf='DEVELOPER';").fetchone()
                if not reg_dev:
                    otp_dev = generate_otp()
                    cur.execute(
                        "INSERT INTO registrations (erf, proxies, otp) VALUES ('DEVELOPER', 0, ?);",
                        (otp_dev,),
                    )
                    conn.commit()
                    flash(f"Developer login created. ERF: DEVELOPER, OTP: {otp_dev}")
                else:
                    if not reg_dev["otp"]:
                        otp_dev = generate_otp()
                        cur.execute(
                            "UPDATE registrations SET otp=? WHERE erf='DEVELOPER';",
                            (otp_dev,),
                        )
                        conn.commit()
                        flash(f"Developer OTP generated: {otp_dev}")
        elif form_type == "add_proxy":
            erf = request.form.get("erf", "").strip().upper()
            note = request.form.get("note", "").strip()
            if not erf:
                flash("ERF is required.")
            else:
                owner = cur.execute("SELECT * FROM owners WHERE erf = ?;", (erf,)).fetchone()
                if not owner:
                    flash(f"No owner found for ERF {erf}.")
                else:
                    try:
                        cur.execute(
                            "INSERT INTO developer_proxies (erf, note) VALUES (?, ?);",
                            (erf, note),
                        )
                        conn.commit()
                        flash(f"ERF {erf} linked to developer.")
                    except sqlite3.IntegrityError:
                        flash(f"ERF {erf} already linked as developer proxy.")
        elif form_type == "delete_proxy":
            pid = request.form.get("proxy_id", "").strip()
            try:
                pid_int = int(pid)
                cur.execute("DELETE FROM developer_proxies WHERE id = ?;", (pid_int,))
                conn.commit()
                flash("Developer proxy removed.")
            except ValueError:
                flash("Invalid proxy ID.")
        conn.close()
        return redirect(url_for("admin_developer"))

    settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
    proxies = cur.execute("""
        SELECT dp.id, dp.erf, dp.note, o.name
        FROM developer_proxies dp
        LEFT JOIN owners o ON o.erf = dp.erf
        ORDER BY dp.erf;
    """).fetchall()
    developer_reg = cur.execute("SELECT * FROM registrations WHERE erf='DEVELOPER';").fetchone()
    conn.close()
    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Developer Settings</h1>
  <form method="post">
    <input type="hidden" name="form_type" value="settings">
    <p><label><input type="checkbox" name="is_active" {% if settings['is_active'] %}checked{% endif %}> Developer applicable</label></p>
    <p><label>Developer base votes:<br><input type="number" name="base_votes" min="0" value="{{ settings['base_votes'] }}"></label></p>
    <p><label>Developer proxy count:<br><input type="number" name="proxy_count" min="0" value="{{ settings['proxy_count'] }}"></label></p>
    <p><label>Comments:<br><textarea name="comment">{{ settings['comment'] or '' }}</textarea></label></p>
    <button type="submit">Save Developer Settings</button>
  </form>
  {% if settings['is_active'] %}
    <hr>
    <h3>Developer Login</h3>
    {% if developer_reg and developer_reg['otp'] %}
      <p>Username/ERF: <code>DEVELOPER</code></p>
      <p>OTP: <code>{{ developer_reg['otp'] }}</code></p>
    {% else %}
      <p class="subtle">Developer is active but OTP not yet generated.</p>
    {% endif %}
  {% endif %}
  <hr>
  <h3>Developer Proxies (linked ERFs)</h3>
  <p class="subtle">Each ERF here is represented by the developer and cannot vote individually.</p>
  <form method="post">
    <input type="hidden" name="form_type" value="add_proxy">
    <p><label>ERF to link:<br><input type="text" name="erf" required></label></p>
    <p><label>Note (optional):<br><textarea name="note"></textarea></label></p>
    <button type="submit">Add Developer Proxy ERF</button>
  </form>
  <h4>Linked Developer ERFs</h4>
  {% if not proxies %}
    <p class="subtle">No ERFs linked to developer yet.</p>
  {% else %}
    <table>
      <tr><th>ERF</th><th>Owner Name</th><th>Note</th><th>Action</th></tr>
      {% for p in proxies %}
        <tr>
          <td>{{ p['erf'] }}</td>
          <td>{{ p['name'] or '' }}</td>
          <td>{{ p['note'] or '' }}</td>
          <td>
            <form method="post" style="display:inline;">
              <input type="hidden" name="form_type" value="delete_proxy">
              <input type="hidden" name="proxy_id" value="{{ p['id'] }}">
              <button type="submit">Remove</button>
            </form>
          </td>
        </tr>
      {% endfor %}
    </table>
  {% endif %}
</div>
""" + BASE_TAIL
    return render_template_string(template, settings=settings, proxies=proxies, developer_reg=developer_reg)


@app.route("/admin/developer/vote/<int:topic_id>", methods=["GET", "POST"])
def admin_developer_vote(topic_id):
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    topic = cur.execute("SELECT * FROM topics WHERE id=?;", (topic_id,)).fetchone()
    if not topic:
        conn.close()
        return "Topic not found", 404
    options = cur.execute("SELECT * FROM options WHERE topic_id=? ORDER BY id;", (topic_id,)).fetchall()
    settings = cur.execute("SELECT * FROM developer_settings WHERE id=1;").fetchone()
    proxies_rows = cur.execute("SELECT COUNT(*) AS c FROM developer_proxies;").fetchone()
    linked_count = proxies_rows["c"] if proxies_rows else 0
    if not settings or not settings["is_active"]:
        conn.close()
        flash("Developer not enabled.")
        return redirect(url_for("admin_topics"))
    base_votes = settings["base_votes"] or 0
    proxy_count = settings["proxy_count"] or 0
    total_weight = base_votes + proxy_count + linked_count
    if total_weight <= 0:
        conn.close()
        flash("Developer has zero total vote weight.")
        return redirect(url_for("admin_topics"))
    if request.method == "POST":
        option_id = request.form.get("option_id", "").strip()
        try:
            opt_id_int = int(option_id)
        except ValueError:
            flash("Invalid option.")
            conn.close()
            return redirect(url_for("admin_developer_vote", topic_id=topic_id))
        existing = cur.execute(
            "SELECT * FROM votes WHERE topic_id=? AND erf='DEVELOPER';",
            (topic_id,),
        ).fetchone()
        if existing:
            flash("Developer already voted on this topic.")
            conn.close()
            return redirect(url_for("admin_developer_vote", topic_id=topic_id))

        # --- cryptographic vote ledger ---
        prev = cur.execute(
            "SELECT vote_hash FROM votes WHERE topic_id=? ORDER BY id DESC LIMIT 1;",
            (topic_id,)
        ).fetchone()

        prev_hash = prev["vote_hash"] if prev else "GENESIS"
        timestamp = datetime.utcnow().isoformat()

        vote_hash = compute_vote_hash(
            prev_hash,
            "DEVELOPER",
            topic_id,
            opt_id_int,
            total_weight,
            timestamp
        )

        cur.execute("""
            INSERT INTO votes (
                topic_id, erf, option_id, weight,
                prev_hash, vote_hash, timestamp
            )
            VALUES (?, 'DEVELOPER', ?, ?, ?, ?, ?);
        """, (
            topic_id,
            opt_id_int,
            total_weight,
            prev_hash,
            vote_hash,
            timestamp
        ))

        conn.commit()
        conn.close()
        flash("Developer vote recorded.")
        return redirect(url_for("admin_topics"))
    conn.close()
    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Developer Vote for Topic: {{ topic['title'] }}</h1>
  <p class="subtle">Developer total vote weight for this vote: {{ total_weight }}</p>
  <form method="post">
    <h3>Options</h3>
    {% for o in options %}
      <p><label><input type="radio" name="option_id" value="{{ o['id'] }}" required> {{ o['label'] }}</label></p>
    {% endfor %}
    <button type="submit">Record Developer Vote</button>
  </form>
  <p><a href="{{ url_for('admin_topics') }}">Back to Topics</a></p>
</div>
""" + BASE_TAIL
    return render_template_string(template, topic=topic, options=options, total_weight=total_weight)


@app.route("/admin/export")
def admin_export():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Export Data</h1>
  <h3>1. Voting Results</h3>
  <p><a href="{{ url_for('admin_export_votes') }}"><button type="button">Download Voting Results CSV</button></a></p>
  <hr>
  <h3>2. Developer Profile</h3>
  <p><a href="{{ url_for('admin_export_developer') }}"><button type="button">Download Developer Profile CSV</button></a></p>
  <hr>
  <h3>3. Registrations & Quorum Data</h3>
  <p><a href="{{ url_for('admin_export_registrations') }}"><button type="button">Download Registrations CSV</button></a></p>
</div>
""" + BASE_TAIL
    return render_template_string(template)

@app.route("/admin/verify")
def admin_verify_chain():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))

    ok = verify_vote_chain()

    if ok:
        return "<h2>Vote chain is VALID</h2>"
    else:
        return "<h2 style='color:red'>Vote chain has been TAMPERED</h2>"

@app.route("/admin/export/votes")
def admin_export_votes():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    rows = cur.execute("""
        SELECT t.id AS topic_id, t.title AS topic_title, o.label AS option_label,
               SUM(v.weight) AS total_votes
        FROM votes v
        JOIN topics t ON t.id = v.topic_id
        JOIN options o ON o.id = v.option_id
        GROUP BY t.id, o.id
        ORDER BY t.id, o.id;
    """).fetchall()
    conn.close()
    text_buffer = StringIO()
    writer = csv.writer(text_buffer)
    writer.writerow(["Topic ID", "Topic Title", "Option", "Total Vote Weight"])
    for r in rows:
        writer.writerow([r["topic_id"], r["topic_title"], r["option_label"], r["total_votes"]])
    csv_bytes = text_buffer.getvalue().encode("utf-8")
    bio = BytesIO(csv_bytes)
    bio.seek(0)
    return send_file(
        bio,
        mimetype="text/csv",
        as_attachment=True,
        download_name="hoa_voting_results.csv",
    )


@app.route("/admin/export/developer")
def admin_export_developer():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
    proxies = cur.execute("""
        SELECT dp.erf, dp.note, o.name
        FROM developer_proxies dp
        LEFT JOIN owners o ON o.erf = dp.erf
        ORDER BY dp.erf;
    """).fetchall()
    total_linked = len(proxies)
    if settings:
        base_votes = settings["base_votes"] or 0
        proxy_count = settings["proxy_count"] or 0
        comment = settings["comment"] or ""
        is_active = settings["is_active"]
        total_weight = base_votes + proxy_count + total_linked
    else:
        base_votes = proxy_count = total_linked = total_weight = is_active = 0
        comment = ""
    conn.close()
    text_buffer = StringIO()
    writer = csv.writer(text_buffer)
    writer.writerow([
        "Section", "ERF", "Owner Name", "Base Votes", "Developer Proxy Count",
        "Developer Comment", "Developer Active (1/0)", "Total Linked ERFs",
        "Total Developer Vote Weight", "Proxy Note",
    ])
    writer.writerow([
        "settings", "DEVELOPER", "", base_votes, proxy_count, comment,
        is_active, total_linked, total_weight, "",
    ])
    for p in proxies:
        writer.writerow([
            "proxy", p["erf"], p["name"] or "", "", "", "", "", "", "", p["note"] or "",
        ])
    csv_bytes = text_buffer.getvalue().encode("utf-8")
    bio = BytesIO(csv_bytes)
    bio.seek(0)
    return send_file(
        bio,
        mimetype="text/csv",
        as_attachment=True,
        download_name="hoa_developer_profile.csv",
    )

@app.route("/admin/export/registrations")
def admin_export_registrations():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))

    conn = get_db()
    cur = conn.cursor()

    # ===============================
    # REGISTERED ERFs ONLY (quorum base)
    # ===============================
    registrations = cur.execute("""
        SELECT r.erf, r.proxies, o.name
        FROM registrations r
        JOIN owners o ON o.erf = r.erf
        ORDER BY r.erf;
    """).fetchall()

    registered_erfs = {r["erf"] for r in registrations}

    # ===============================
    # Proxy / Developer data
    # ===============================
    dev_proxies_rows = cur.execute("SELECT erf FROM developer_proxies;").fetchall()
    dev_proxy_erfs = {row["erf"] for row in dev_proxies_rows}

    owner_proxies_rows = cur.execute("SELECT primary_erf, proxy_erf FROM owner_proxies;").fetchall()
    owner_proxy_map = {row["proxy_erf"]: row["primary_erf"] for row in owner_proxies_rows}

    primary_link_counts = {}
    for row in owner_proxies_rows:
        primary_link_counts[row["primary_erf"]] = primary_link_counts.get(row["primary_erf"], 0) + 1

    settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
    dev_linked_count_row = cur.execute("SELECT COUNT(*) AS c FROM developer_proxies;").fetchone()

    if settings:
        base_votes = settings["base_votes"] or 0
        proxy_count = settings["proxy_count"] or 0
        dev_linked_count = dev_linked_count_row["c"] if dev_linked_count_row else 0
        dev_total_weight = base_votes + proxy_count + dev_linked_count
        dev_active = settings["is_active"]
    else:
        base_votes = proxy_count = dev_linked_count = dev_total_weight = dev_active = 0

    conn.close()
    # ===============================
    # CSV generation
    # ===============================
    text_buffer = StringIO()
    writer = csv.writer(text_buffer)

    writer.writerow([
        "ERF", "Owner Name", "Registered?", "Numeric Proxies",
        "Linked ERFs (owner proxies)", "Total Vote Weight",
        "Is Developer", "Blocked?", "Blocked By"
    ])

    running_total = 0

    # ===============================
    # Registered owners
    # ===============================
    for r in registrations:
        erf = r["erf"]
        name = r["name"] or ""
        numeric_proxies = r["proxies"] or 0

        blocked = "No"
        blocked_by = ""

        if erf in dev_proxy_erfs:
            blocked = "Yes"
            blocked_by = "Developer"
        elif erf in owner_proxy_map:
            blocked = "Yes"
            blocked_by = f"Owner proxy holder: {owner_proxy_map[erf]}"

        linked = primary_link_counts.get(erf, 0)

        total_weight = 1 + numeric_proxies + linked if blocked == "No" else 0

        running_total += total_weight

        writer.writerow([
            erf, name, "Yes", numeric_proxies,
            linked, total_weight,
            "No", blocked, blocked_by
        ])

    # ===============================
    # Developer (separate weighted voter)
    # ===============================
    if dev_active:
        running_total += dev_total_weight

        writer.writerow([
            "DEVELOPER",
            "",
            "Yes",
            proxy_count,
            dev_linked_count,
            dev_total_weight,
            "Yes",
            "No",
            ""
        ])

    # ===============================
    # Totals
    # ===============================
    writer.writerow([])
    writer.writerow([
        "TOTAL REGISTERED ERFs",
        len(registered_erfs) + (1 if dev_active else 0)
    ])
    writer.writerow([
        "TOTAL VOTE WEIGHT",
        running_total
    ])

    output = BytesIO()
    output.write(text_buffer.getvalue().encode())
    output.seek(0)

    return send_file(
        output,
        mimetype="text/csv",
        as_attachment=True,
        download_name="hoa_registrations_quorum.csv"
    )

@app.route("/admin/reset", methods=["GET", "POST"])
def admin_reset():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))

    # 🔐 Always ensure this HOA has its schema
    ensure_schema()

    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        # Wipe ONLY this HOA database
        cur.execute("DELETE FROM owners;")
        cur.execute("DELETE FROM registrations;")
        cur.execute("DELETE FROM owner_proxies;")
        cur.execute("DELETE FROM topics;")
        cur.execute("DELETE FROM options;")
        cur.execute("DELETE FROM votes;")
        cur.execute("DELETE FROM developer_proxies;")

        # Reset developer settings safely
        cur.execute("""
            UPDATE developer_settings
            SET is_active=0, base_votes=0, proxy_count=0, comment=NULL
            WHERE id=1
        """)

        conn.commit()
        conn.close()

        return redirect("/admin")

    return render_template_string("""
    <div style="padding:30px">
        <h2>Reset All HOA Data</h2>
        <p><b>This will permanently erase all voting data for THIS HOA ONLY.</b></p>
        <form method="post">
            <button style="background:red;color:white;padding:10px">
                RESET THIS HOA
            </button>
        </form>
    </div>
    """)

# ---------- PUBLIC VOTING ----------

@app.route("/vote/login", methods=["GET", "POST"])
def vote_login():
    if request.method == "POST":
        erf = request.form.get("erf", "").strip().upper()
        otp_input = request.form.get("otp", "").strip().upper()
        if not erf or not otp_input:
            flash("Both ERF and OTP are required.")
            return redirect(url_for("vote_login"))

        conn = get_db()
        cur = conn.cursor()

        settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
        if erf == "DEVELOPER":
            if not settings or not settings["is_active"]:
                conn.close()
                flash("Developer is not enabled for this association.")
                return redirect(url_for("vote_login"))

        dev_proxy = cur.execute("SELECT 1 FROM developer_proxies WHERE erf=?;", (erf,)).fetchone()
        owner_proxy = cur.execute("SELECT 1 FROM owner_proxies WHERE proxy_erf=?;", (erf,)).fetchone()
        if dev_proxy and erf != "DEVELOPER":
            conn.close()
            flash("This ERF is linked to the developer and cannot vote individually.")
            return redirect(url_for("vote_login"))
        if owner_proxy and erf != "DEVELOPER":
            conn.close()
            flash("This ERF is represented by another owner and cannot vote individually.")
            return redirect(url_for("vote_login"))

        reg = cur.execute("SELECT * FROM registrations WHERE erf=?;", (erf,)).fetchone()
        conn.close()
        if not reg or not reg["otp"]:
            flash("Invalid ERF or OTP.")
            return redirect(url_for("vote_login"))
        if reg["otp"].upper() != otp_input:
            flash("Invalid ERF or OTP.")
            return redirect(url_for("vote_login"))

        session["voter_erf"] = erf
        flash(f"Logged in as ERF {erf} for voting.")
        return redirect(url_for("vote_topic_selector"))

    template = BASE_HEAD_PUBLIC + """
<div class="card">
  <h1>Voting Login</h1>
  <form method="post">
    <p><label>ERF:<br><input type="text" name="erf" required></label></p>
    <p><label>One-Time PIN:<br><input type="password" name="otp" required></label></p>
    <button type="submit">Login</button>
  </form>
</div>
""" + BASE_TAIL
    return render_template_string(template)


@app.route("/vote/logout")
def vote_logout():
    session.pop("voter_erf", None)
    flash("You have been logged out from voting.")
    return redirect(url_for("vote_login"))


@app.route("/vote")
def vote_topic_selector():
    erf = session.get("voter_erf")
    if not erf:
        return redirect(url_for("vote_login"))
    conn = get_db()
    cur = conn.cursor()
    topics = cur.execute("SELECT * FROM topics WHERE is_open=1 ORDER BY id DESC;").fetchall()
    conn.close()
    template = BASE_HEAD_PUBLIC + """
<div class="card">
  <h1>Owner Voting</h1>
  <p>Logged in as ERF <strong>{{ erf }}</strong>. <a href="{{ url_for('vote_logout') }}">Logout</a></p>
  {% if not topics %}
    <p>No open voting topics.</p>
  {% else %}
    <p>Select a topic:</p>
    <ul>
      {% for t in topics %}
        <li><a href="{{ url_for('vote_topic', topic_id=t['id']) }}">{{ t['title'] }}</a></li>
      {% endfor %}
    </ul>
  {% endif %}
</div>
""" + BASE_TAIL
    return render_template_string(template, erf=erf, topics=topics)


@app.route("/vote/<int:topic_id>", methods=["GET", "POST"])
def vote_topic(topic_id):
    erf = session.get("voter_erf")
    if not erf:
        return redirect(url_for("vote_login"))
    conn = get_db()
    cur = conn.cursor()
    # --- Phase 4.1: Topic locking ---
    topic = cur.execute(
        "SELECT is_open FROM topics WHERE id=?",
        (topic_id,)
    ).fetchone()

    if not topic or topic["is_open"] == 0:
        flash("This topic is closed.")
        conn.close()
        return redirect("/vote")

    topic = cur.execute("SELECT * FROM topics WHERE id=?;", (topic_id,)).fetchone()
    if not topic or not topic["is_open"]:
        conn.close()
        template = BASE_HEAD_PUBLIC + "<div class='card'><h1>Voting not available for this topic.</h1></div>" + BASE_TAIL
        return render_template_string(template)
    options = cur.execute("SELECT * FROM options WHERE topic_id=? ORDER BY id;", (topic_id,)).fetchall()
    if request.method == "POST":
        option_id = request.form.get("option_id", "").strip()
        if not option_id:
            flash("Please select an option.")
            conn.close()
            return redirect(url_for("vote_topic", topic_id=topic_id))
        reg = cur.execute("SELECT * FROM registrations WHERE erf=?;", (erf,)).fetchone()
        if not reg:
            flash(f"ERF {erf} is not registered.")
            conn.close()
            return redirect(url_for("vote_topic", topic_id=topic_id))
        existing = cur.execute(
            "SELECT * FROM votes WHERE topic_id=? AND erf=?;",
            (topic_id, erf),
        ).fetchone()
        if existing:
            flash("This ERF has already voted on this topic.")
            conn.close()
            return redirect(url_for("vote_topic", topic_id=topic_id))
        try:
            opt_id_int = int(option_id)
        except ValueError:
            flash("Invalid option.")
            conn.close()
            return redirect(url_for("vote_topic", topic_id=topic_id))

        if erf == "DEVELOPER":
            settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
            proxies_rows = cur.execute("SELECT COUNT(*) AS c FROM developer_proxies;").fetchone()
            linked_count = proxies_rows["c"] if proxies_rows else 0
            if not settings or not settings["is_active"]:
                flash("Developer not enabled.")
                conn.close()
                return redirect(url_for("vote_topic", topic_id=topic_id))
            base_votes = settings["base_votes"] or 0
            proxy_count = settings["proxy_count"] or 0
            total_weight = base_votes + proxy_count + linked_count
            if total_weight <= 0:
                flash("Developer has zero vote weight.")
                conn.close()
                return redirect(url_for("vote_topic", topic_id=topic_id))
            weight = total_weight
        else:
            linked_count_row = cur.execute(
                "SELECT COUNT(*) AS c FROM owner_proxies WHERE primary_erf=?;",
                (erf,),
            ).fetchone()
            linked_count = linked_count_row["c"] if linked_count_row else 0
            weight = 1 + (reg["proxies"] or 0) + linked_count

        # --- cryptographic vote ledger ---
        prev = cur.execute(
            "SELECT vote_hash FROM votes WHERE topic_id=? ORDER BY id DESC LIMIT 1;",
            (topic_id,)
        ).fetchone()

        prev_hash = prev["vote_hash"] if prev else "GENESIS"
        timestamp = datetime.utcnow().isoformat()

        vote_hash = compute_vote_hash(
            prev_hash,
            erf,
            topic_id,
            opt_id_int,
            weight,
            timestamp
        )

        cur.execute("""
            INSERT INTO votes (
                topic_id, erf, option_id, weight,
                prev_hash, vote_hash, timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (
            topic_id,
            erf,
            opt_id_int,
            weight,
            prev_hash,
            vote_hash,
            timestamp
        ))

        conn.commit()
        conn.close()

        template = BASE_HEAD_PUBLIC + "<div class='card'><h1>Thank you, your vote has been recorded.</h1></div>" + BASE_TAIL
        return render_template_string(template)

    # ---------- GET request (show ballot) ----------
    conn.close()
    template = BASE_HEAD_PUBLIC + """
<div class="card">
  <h1>Voting Ballot</h1>
  <p>Logged in as ERF <strong>{{ erf }}</strong>. 
     <a href="{{ url_for('vote_logout') }}">Logout</a></p>
  <h2>{{ topic['title'] }}</h2>
  <p>{{ topic['description'] }}</p>
  <form method="post">
    <h3>Options</h3>
    {% for o in options %}
      <p>
        <label>
          <input type="radio" name="option_id" value="{{ o['id'] }}" required>
          {{ o['label'] }}
        </label>
      </p>
    {% endfor %}
    <button type="submit">Submit Vote</button>
  </form>
</div>
""" + BASE_TAIL

    return render_template_string(template, erf=erf, topic=topic, options=options)


# ---------- QR / SCAN FEATURES ----------

@app.route("/admin/scan_register", methods=["GET", "POST"])
def admin_scan_register():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    if request.method == "POST":
        scanned_raw = request.form.get("scanned", "").strip()
        scanned = scanned_raw.upper()
        if not scanned_raw:
            flash("Nothing scanned.")
            conn.close()
            return redirect(url_for("admin_scan_register"))

        # Try match as ERF first
        owner = cur.execute("SELECT * FROM owners WHERE erf=?;", (scanned,)).fetchone()
        # If not found, try match by ID number (using raw value, not uppercased)
        if not owner and scanned != "DEVELOPER":
            owner = cur.execute("SELECT * FROM owners WHERE id_number=?;", (scanned_raw,)).fetchone()

        if scanned != "DEVELOPER" and not owner:
            flash(f"No owner found for scanned value '{scanned_raw}'. Check ERF/ID mapping in Owners.")
            conn.close()
            return redirect(url_for("admin_scan_register"))

        if scanned == "DEVELOPER":
            target_erf = "DEVELOPER"
        else:
            target_erf = owner["erf"]

        otp = generate_otp()
        cur.execute(
            "INSERT INTO registrations (erf, proxies, otp) VALUES (?, 0, ?) "
            "ON CONFLICT(erf) DO UPDATE SET otp=excluded.otp;",
            (target_erf, otp),
        )
        conn.commit()
        conn.close()

        quick_url = url_for("vote_quick", _external=True) + f"?erf={target_erf}&otp={otp}"
        template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Scanned: {{ erf }}</h1>
  <p>One-time PIN: <code>{{ otp }}</code></p>
  <p>Have the owner scan this QR code with their phone to open the voting portal (auto-login):</p>
  <p><img src="{{ url_for('qr_image', erf=erf) }}" alt="QR code"></p>
  <p>Or open this link on their phone: <br><a href="{{ quick_url }}">{{ quick_url }}</a></p>
  <p><a href="{{ url_for('admin_registrations') }}">Back to Registrations</a></p>
</div>
""" + BASE_TAIL
        return render_template_string(template, erf=target_erf, otp=otp, quick_url=quick_url)

    conn.close()
    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Scan owner ID</h1>
  <p class="subtle">
    Focus the box below and scan either the ERF barcode or the owner's ID number.
    The scanner should type the code and press Enter.
  </p>
  <form method="post">
    <p><label>Scanned value (ERF or ID):<br><input type="text" name="scanned" autofocus></label></p>
    <button type="submit">Submit</button>
  </form>
</div>
""" + BASE_TAIL
    return render_template_string(template)


BASE_TAIL = """
</div>
</body>
</html>
"""

@app.route("/qr/<erf>")
def qr_image(erf):
    conn = get_db()
    cur = conn.cursor()
    erf_up = erf.strip().upper()
    reg = cur.execute("SELECT otp FROM registrations WHERE erf=?;", (erf_up,)).fetchone()
    conn.close()
    if not reg or not reg["otp"]:
        return "No registration/OTP for that ERF", 404
    otp = reg["otp"]
    quick_url = url_for("vote_quick", _external=True) + f"?erf={erf_up}&otp={otp}"
    img = qrcode.make(quick_url)
    bio = BytesIO()
    img.save(bio, format="PNG")
    bio.seek(0)
    return send_file(bio, mimetype="image/png")


@app.route("/vote/quick")
def vote_quick():
    erf = request.args.get("erf", "").strip().upper()
    otp = request.args.get("otp", "").strip().upper()
    if not erf or not otp:
        flash("Missing ERF or PIN.")
        return redirect(url_for("vote_login"))

    conn = get_db()
    cur = conn.cursor()

    dev_proxy = cur.execute("SELECT 1 FROM developer_proxies WHERE erf=?;", (erf,)).fetchone()
    owner_proxy = cur.execute("SELECT 1 FROM owner_proxies WHERE proxy_erf=?;", (erf,)).fetchone()
    if dev_proxy and erf != "DEVELOPER":
        conn.close()
        flash("This ERF is linked to the developer and cannot vote individually.")
        return redirect(url_for("vote_login"))
    if owner_proxy and erf != "DEVELOPER":
        conn.close()
        flash("This ERF is represented by another owner and cannot vote individually.")
        return redirect(url_for("vote_login"))

    reg = cur.execute("SELECT * FROM registrations WHERE erf=?;", (erf,)).fetchone()
    conn.close()
    if not reg or not reg["otp"] or reg["otp"].upper() != otp:
        flash("Invalid or expired PIN.")
        return redirect(url_for("vote_login"))

    session["voter_erf"] = erf
    return redirect(url_for("vote_topic_selector"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)

