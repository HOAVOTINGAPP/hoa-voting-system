import os
import csv
import sqlite3
import random
import string
from io import StringIO, BytesIO
from flask import Flask, request, redirect, url_for, render_template_string, send_file, flash, session

app = Flask(__name__)
app.secret_key = "change_this_to_any_random_string"  # change for production

DB_NAME = "hoa_meeting.db"
ADMIN_PASSWORD = "hoaadmin"  # change for production


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS owners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            erf TEXT UNIQUE NOT NULL,
            name TEXT
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

    # Developer config: single settings row + list of ERFs linked to developer
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

    # Owner proxies table (per-owner linked ERFs)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS owner_proxies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            primary_erf TEXT NOT NULL,
            proxy_erf TEXT UNIQUE NOT NULL
        );
    """)

    # Ensure a default developer_settings row exists
    existing = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
    if not existing:
        cur.execute(
            "INSERT INTO developer_settings (id, is_active, base_votes, proxy_count, comment) VALUES (1, 0, 0, 0, '');"
        )

    conn.commit()
    conn.close()


def generate_otp(length=6):
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


# Admin layout (with navigation)
BASE_HEAD_ADMIN = """<!doctype html>
<html>
<head>
    <title>HOA AGM App - Admin</title>
    <meta charset="utf-8">
    <style>
        :root {
            --bg: #0f172a;
            --bg-page: #f3f4f6;
            --card-bg: #ffffff;
            --accent: #2563eb;
            --accent-dark: #1d4ed8;
            --danger: #b91c1c;
            --success: #166534;
            --border-subtle: #e5e7eb;
            --text-main: #111827;
            --text-muted: #6b7280;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: var(--bg-page);
            color: var(--text-main);
        }
        .shell {
            max-width: 1024px;
            margin: 0 auto;
            padding: 24px 16px 40px;
        }
        nav {
            background: var(--bg);
            padding: 12px 16px;
            margin: 0 -16px 12px;
            box-shadow: 0 10px 30px rgba(15, 23, 42, 0.4);
            position: sticky;
            top: 0;
            z-index: 10;
        }
        nav a {
            color: #e5e7eb;
            text-decoration: none;
            margin-right: 16px;
            font-size: 14px;
            font-weight: 500;
        }
        nav a:hover {
            color: #ffffff;
            text-decoration: underline;
        }
        h1 {
            font-size: 26px;
            margin: 0 0 8px;
        }
        h2 {
            font-size: 20px;
            margin-top: 0;
        }
        h3 {
            font-size: 16px;
            margin-bottom: 4px;
        }
        p {
            color: var(--text-muted);
            font-size: 14px;
        }
        .card {
            background: var(--card-bg);
            border-radius: 14px;
            padding: 20px 22px;
            box-shadow: 0 14px 35px rgba(15, 23, 42, 0.12);
            margin-top: 16px;
        }
        form {
            margin-top: 10px;
        }
        label {
            display: inline-block;
            margin: 4px 0;
            font-size: 14px;
        }
        input[type="text"],
        input[type="number"],
        input[type="password"],
        input[type="file"],
        textarea {
            font-family: inherit;
            border-radius: 10px;
            border: 1px solid var(--border-subtle);
            padding: 8px 10px;
            width: 100%;
            max-width: 360px;
            font-size: 14px;
            margin-top: 4px;
        }
        textarea {
            resize: vertical;
            min-height: 80px;
        }
        button {
            background: var(--accent);
            border: none;
            border-radius: 999px;
            padding: 8px 20px;
            color: #ffffff;
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            margin-top: 10px;
        }
        button:hover {
            background: var(--accent-dark);
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
            font-size: 13px;
            background: #ffffff;
            border-radius: 12px;
            overflow: hidden;
        }
        th, td {
            border: 1px solid var(--border-subtle);
            padding: 8px 10px;
            text-align: left;
        }
        th {
            background: #e5e7eb;
            font-weight: 600;
        }
        code {
            background: #111827;
            color: #e5e7eb;
            padding: 2px 6px;
            border-radius: 6px;
            font-size: 12px;
        }
        ul {
            padding-left: 18px;
        }
        li.error {
            color: var(--danger);
            font-weight: 500;
        }
        li.success {
            color: var(--success);
            font-weight: 500;
        }
        .subtle {
            font-size: 12px;
            color: var(--text-muted);
        }
        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 999px;
            font-size: 11px;
            background: #fee2e2;
            color: #b91c1c;
        }
    </style>
</head>
<body>
<div class="shell">
<nav>
    <a href="{{ url_for('admin_dashboard') }}">Admin Home</a>
    <a href="{{ url_for('admin_owners') }}">Owners</a>
    <a href="{{ url_for('admin_registrations') }}">Registrations</a>
    <a href="{{ url_for('admin_topics') }}">Topics & Voting</a>
    <a href="{{ url_for('admin_developer') }}">Developer</a>
    <a href="{{ url_for('admin_export') }}">Export Results</a>
    <a href="{{ url_for('admin_reset') }}">Reset All</a>
    <a href="{{ url_for('admin_logout') }}">Logout</a>
</nav>
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}
    <ul>
    {% for category, msg in messages %}
      <li class="{{ category }}">{{ msg }}</li>
    {% endfor %}
    </ul>
  {% endif %}
{% endwith %}
"""

# Public layout (no admin navigation)
BASE_HEAD_PUBLIC = """<!doctype html>
<html>
<head>
    <title>HOA AGM Voting</title>
    <meta charset="utf-8">
    <style>
        :root {
            --bg-page: #f3f4f6;
            --card-bg: #ffffff;
            --accent: #2563eb;
            --accent-dark: #1d4ed8;
            --danger: #b91c1c;
            --success: #166534;
            --border-subtle: #e5e7eb;
            --text-main: #111827;
            --text-muted: #6b7280;
        }
        * { box-sizing: border-box; }
        body {
            margin: 0;
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: var(--bg-page);
            color: var(--text-main);
        }
        .shell {
            max-width: 640px;
            margin: 0 auto;
            padding: 32px 16px 40px;
        }
        h1 {
            font-size: 24px;
            margin: 0 0 10px;
        }
        h2 {
            font-size: 20px;
            margin-top: 0;
        }
        h3 {
            font-size: 16px;
        }
        p {
            color: var(--text-muted);
            font-size: 14px;
        }
        .card {
            background: var(--card-bg);
            border-radius: 14px;
            padding: 20px 22px;
            box-shadow: 0 14px 35px rgba(15, 23, 42, 0.12);
            margin-top: 16px;
        }
        form {
            margin-top: 10px;
        }
        label {
            display: block;
            margin: 6px 0;
            font-size: 14px;
        }
        input[type="text"],
        input[type="password"],
        textarea {
            font-family: inherit;
            border-radius: 10px;
            border: 1px solid var(--border-subtle);
            padding: 8px 10px;
            width: 100%;
            font-size: 14px;
            margin-top: 4px;
        }
        textarea {
            resize: vertical;
            min-height: 80px;
        }
        button {
            background: #2563eb;
            border: none;
            border-radius: 999px;
            padding: 8px 20px;
            color: #ffffff;
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            margin-top: 10px;
        }
        button:hover {
            background: #1d4ed8;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
            font-size: 13px;
            background: #ffffff;
            border-radius: 12px;
            overflow: hidden;
        }
        th, td {
            border: 1px solid var(--border-subtle);
            padding: 8px 10px;
            text-align: left;
        }
        th {
            background: #e5e7eb;
            font-weight: 600;
        }
        ul {
            padding-left: 18px;
        }
        li.error {
            color: var(--danger);
            font-weight: 500;
        }
        li.success {
            color: var(--success);
            font-weight: 500;
        }
        .subtle {
            font-size: 12px;
            color: var(--text-muted);
        }
    </style>
</head>
<body>
<div class="shell">
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}
    <ul>
    {% for category, msg in messages %}
      <li class="{{ category }}">{{ msg }}</li>
    {% endfor %}
    </ul>
  {% endif %}
{% endwith %}
"""

BASE_TAIL = """
</div>
</body>
</html>
"""


def admin_logged_in():
    return session.get("admin_logged_in", False)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            flash(("success", "Logged in as admin."))
            return redirect(url_for("admin_dashboard"))
        else:
            flash(("error", "Incorrect password."))
    # simple login form, no nav
    template = """<!doctype html>
<html>
<head>
    <title>Admin Login - HOA AGM</title>
    <meta charset="utf-8">
    <style>
        body {
            font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #f3f4f6;
            margin: 0;
        }
        .shell {
            max-width: 420px;
            margin: 0 auto;
            padding: 40px 16px;
        }
        .card {
            background: #ffffff;
            border-radius: 14px;
            padding: 22px 24px;
            box-shadow: 0 14px 35px rgba(15, 23, 42, 0.12);
        }
        h1 {
            margin-top: 0;
            font-size: 22px;
        }
        label {
            display: block;
            margin: 8px 0 4px;
            font-size: 14px;
        }
        input[type="password"] {
            width: 100%;
            border-radius: 10px;
            border: 1px solid #e5e7eb;
            padding: 8px 10px;
            font-size: 14px;
        }
        button {
            background: #2563eb;
            border: none;
            border-radius: 999px;
            padding: 8px 20px;
            color: #ffffff;
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            margin-top: 12px;
        }
        button:hover {
            background: #1d4ed8;
        }
        ul { padding-left: 18px; }
        li.error { color: #b91c1c; }
        li.success { color: #166534; }
    </style>
</head>
<body>
<div class="shell">
<div class="card">
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}
    <ul>
    {% for category, msg in messages %}
      <li class="{{ category }}">{{ msg }}</li>
    {% endfor %}
    </ul>
  {% endif %}
{% endwith %}
<h1>Admin Login</h1>
<form method="post">
    <p><label>Password:<br><input type="password" name="password" autofocus required></label></p>
    <button type="submit">Login</button>
</form>
</div>
</div>
</body>
</html>
"""
    return render_template_string(template)


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    flash(("success", "Logged out."))
    return redirect(url_for("admin_login"))


@app.route("/admin")
def admin_dashboard():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    vote_url = url_for('vote_topic_selector', _external=True)
    template = BASE_HEAD_ADMIN + f"""
<div class="card">
  <h1>HOA AGM Admin Dashboard</h1>
  <p>Use the navigation links above to manage owners, registrations, topics, developer voting, export, and reset.</p>
  <p class="subtle">Voting link for owners (and developer) when a topic is open:<br>
     <code>{vote_url}</code>
  </p>
</div>
""" + BASE_TAIL
    return render_template_string(template)


@app.route("/admin/owners", methods=["GET", "POST"])
def admin_owners():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        file = request.files.get("file")
        if not file or file.filename == "":
            flash(("error", "Please choose a CSV file to upload."))
            conn.close()
            return redirect(url_for("admin_owners"))

        try:
            stream = StringIO(file.stream.read().decode("utf-8"))
            reader = csv.reader(stream)
            count = 0
            for row in reader:
                if not row:
                    continue
                if row[0].strip().lower() == "erf":
                    continue
                erf = row[0].strip()
                name = row[1].strip() if len(row) > 1 else ""
                if not erf:
                    continue
                cur.execute(
                    "INSERT OR IGNORE INTO owners (erf, name) VALUES (?, ?);",
                    (erf, name),
                )
                count += 1
            conn.commit()
            flash(("success", f"Owners uploaded/updated: {count}"))
        except Exception as e:
            flash(("error", f"Error reading CSV: {e}"))
        conn.close()
        return redirect(url_for("admin_owners"))

    owners = cur.execute("SELECT * FROM owners ORDER BY erf;").fetchall()
    conn.close()

    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Owners</h1>
  <h3>Upload Owners CSV</h3>
  <p>CSV format: <code>erf,owner_name</code>. You can export from Excel as CSV.</p>
  <form method="post" enctype="multipart/form-data">
      <input type="file" name="file" accept=".csv">
      <br>
      <button type="submit">Upload</button>
  </form>
  <hr>
  <h3>Current Owners</h3>
  <table>
      <tr><th>ERF</th><th>Name</th></tr>
      {% for o in owners %}
      <tr>
          <td>{{ o['erf'] }}</td>
          <td>{{ o['name'] }}</td>
      </tr>
      {% endfor %}
  </table>
</div>
""" + BASE_TAIL
    return render_template_string(template, owners=owners)


@app.route("/admin/registrations", methods=["GET", "POST"])
def admin_registrations():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        form_type = request.form.get("form_type", "register")

        # --- Register / update ERF (numeric proxies as before) ---
        if form_type == "register":
            erf = request.form.get("erf", "").strip()
            proxies = request.form.get("proxies", "0").strip()
            if not erf:
                flash(("error", "ERF is required."))
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
                # Allow DEVELOPER without owner in owners table
                flash(("error", f"No owner found for ERF {erf}. Please upload owner data first."))
                conn.close()
                return redirect(url_for("admin_registrations"))

            otp = generate_otp()

            cur.execute("""
                INSERT INTO registrations (erf, proxies, otp)
                VALUES (?, ?, ?)
                ON CONFLICT(erf) DO UPDATE SET proxies=excluded.proxies, otp=excluded.otp;
            """, (erf, proxies_int, otp))
            conn.commit()
            flash(("success", f"Registered ERF {erf} with {proxies_int} numeric proxies. One-time PIN: {otp}"))

        # --- Add owner proxy (linked ERF) ---
        elif form_type == "add_owner_proxy":
            primary_erf = request.form.get("primary_erf", "").strip().upper()
            proxy_erf = request.form.get("proxy_erf", "").strip().upper()

            if not primary_erf or not proxy_erf:
                flash(("error", "Both 'proxy holder ERF' and 'ERF to link' are required."))
                conn.close()
                return redirect(url_for("admin_registrations"))

            if primary_erf == proxy_erf:
                flash(("error", "An ERF cannot be a proxy for itself."))
                conn.close()
                return redirect(url_for("admin_registrations"))

            # Check both ERFs exist as owners (except DEVELOPER which is allowed as primary only)
            owner_primary = cur.execute("SELECT * FROM owners WHERE erf = ?;", (primary_erf,)).fetchone()
            owner_proxy = cur.execute("SELECT * FROM owners WHERE erf = ?;", (proxy_erf,)).fetchone()

            if not owner_primary and primary_erf != "DEVELOPER":
                flash(("error", f"No owner found for proxy holder ERF {primary_erf}."))
                conn.close()
                return redirect(url_for("admin_registrations"))

            if not owner_proxy:
                flash(("error", f"No owner found for ERF to link: {proxy_erf}."))
                conn.close()
                return redirect(url_for("admin_registrations"))

            # Make sure this ERF is not already linked as a developer proxy
            dev_existing = cur.execute(
                "SELECT 1 FROM developer_proxies WHERE erf = ?;",
                (proxy_erf,)
            ).fetchone()
            if dev_existing:
                flash(("error", f"ERF {proxy_erf} is already linked to the developer and cannot be used as an owner proxy."))
                conn.close()
                return redirect(url_for("admin_registrations"))

            # Insert owner proxy link
            try:
                cur.execute("""
                    INSERT INTO owner_proxies (primary_erf, proxy_erf) VALUES (?, ?);
                """, (primary_erf, proxy_erf))
                conn.commit()
                flash(("success", f"ERF {proxy_erf} is now represented by ERF {primary_erf} and cannot vote individually."))
            except sqlite3.IntegrityError:
                flash(("error", f"ERF {proxy_erf} is already linked as a proxy."))

        # --- Remove owner proxy link ---
        elif form_type == "delete_owner_proxy":
            proxy_id = request.form.get("owner_proxy_id", "").strip()
            try:
                proxy_id_int = int(proxy_id)
                cur.execute("DELETE FROM owner_proxies WHERE id = ?;", (proxy_id_int,))
                conn.commit()
                flash(("success", "Owner proxy link removed."))
            except ValueError:
                flash(("error", "Invalid owner proxy ID."))

        conn.close()
        return redirect(url_for("admin_registrations"))

    # --- GET: show registrations table and owner proxy list ---
    regs = cur.execute("""
        SELECT r.erf, r.proxies, r.otp, o.name
        FROM registrations r
        LEFT JOIN owners o ON o.erf = r.erf
        ORDER BY r.erf;
    """).fetchall()

    dev_proxies_rows = cur.execute("SELECT erf FROM developer_proxies;").fetchall()
    dev_proxy_erfs = [row["efr"] if "efr" in row.keys() else row["erf"] for row in dev_proxies_rows]

    # get owner proxies
    owner_proxies_rows = cur.execute("""
        SELECT op.id, op.primary_erf, op.proxy_erf, o.name
        FROM owner_proxies op
        LEFT JOIN owners o ON o.erf = op.proxy_erf
        ORDER BY op.primary_erf, op.proxy_erf;
    """).fetchall()

    # developer total weight (as before)
    dev_settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
    dev_linked_count_row = cur.execute("SELECT COUNT(*) AS c FROM developer_proxies;").fetchone()
    if dev_settings:
        base_votes = dev_settings["base_votes"] or 0
        proxy_count = dev_settings["proxy_count"] or 0
        linked_count = dev_linked_count_row["c"] if dev_linked_count_row else 0
        dev_total_weight = base_votes + proxy_count + linked_count
    else:
        dev_total_weight = 0

    conn.close()

    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Registrations & Proxies</h1>

  <h3>Register Owner / Update Numeric Proxies</h3>
  <form method="post">
      <input type="hidden" name="form_type" value="register">
      <p><label>ERF:<br><input type="text" name="erf" required></label></p>
      <p><label>Numeric Proxies:<br><input type="number" name="proxies" min="0" value="0"></label></p>
      <button type="submit">Save</button>
  </form>

  <hr>

  <h3>Owner Proxies (linked ERFs)</h3>
  <p class="subtle">
    Each ERF linked here is considered represented by the specified owner and cannot log in to vote individually.
  </p>
  <form method="post">
      <input type="hidden" name="form_type" value="add_owner_proxy">
      <p><label>Proxy holder ERF (who will vote):<br><input type="text" name="primary_erf" required></label></p>
      <p><label>ERF to link:<br><input type="text" name="proxy_erf" required></label></p>
      <button type="submit">Add Owner Proxy ERF</button>
  </form>

  <h4>Linked Owner ERFs</h4>
  {% if not owner_proxies %}
    <p class="subtle">No ERFs linked as owner proxies yet.</p>
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
            <input type="hidden" name="form_type" value="delete_owner_proxy">
            <input type="hidden" name="owner_proxy_id" value="{{ p['id'] }}">
            <button type="submit">Remove</button>
          </form>
        </td>
      </tr>
      {% endfor %}
    </table>
  {% endif %}

  <hr>

  <h3>Registered ERFs</h3>
  <p class="subtle">
    ERFs linked to the developer or as owner proxies are blocked from individual voting.
    For DEVELOPER, the Total Vote Weight shown is: base votes + developer proxy count + number of linked ERFs.
  </p>
  <table>
      <tr><th>ERF</th><th>Owner Name</th><th>Numeric Proxies</th><th>Total Vote Weight</th><th>One-Time PIN</th><th>Developer Proxy?</th></tr>
      {% for r in regs %}
      <tr>
          <td>{{ r['erf'] }}</td>
          <td>{{ r['name'] or '' }}</td>
          <td>{{ r['proxies'] }}</td>
          <td>
            {% if r['erf'] == 'DEVELOPER' %}
              {{ dev_total_weight }}
            {% else %}
              {{ 1 + (r['proxies'] or 0) }}
            {% endif %}
          </td>
          <td><code>{{ r['otp'] or '' }}</code></td>
          <td>
            {% if r['erf'] in dev_proxy_erfs %}
              <span class="badge">Developer proxy</span>
            {% else %}
              -
            {% endif %}
          </td>
      </tr>
      {% endfor %}
  </table>
</div>
""" + BASE_TAIL
    return render_template_string(
        template,
        regs=regs,
        dev_proxy_erfs=dev_proxy_erfs,
        dev_total_weight=dev_total_weight,
        owner_proxies=owner_proxies_rows,
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
            flash(("error", "Topic title is required."))
        else:
            cur.execute("INSERT INTO topics (title, description, is_open) VALUES (?, ?, 0);",
                        (title, description))
            conn.commit()
            flash(("success", "Topic created."))
        conn.close()
        return redirect(url_for("admin_topics"))

    topics = cur.execute("SELECT * FROM topics ORDER BY id DESC;").fetchall()

    dev_settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
    dev_active = bool(dev_settings["is_active"]) if dev_settings else False

    conn.close()

    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Topics & Voting</h1>
  <h3>Create New Topic</h3>
  <form method="post">
      <p><label>Title:<br><input type="text" name="title" required></label></p>
      <p><label>Description (optional):<br>
         <textarea name="description" rows="3" cols="50"></textarea></label></p>
      <button type="submit">Create Topic</button>
  </form>
  <hr>
  <h3>Existing Topics</h3>
  <table>
      <tr><th>ID</th><th>Title</th><th>Open?</th><th>Options</th><th>Developer Vote</th><th>Actions</th></tr>
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
              {% if t['is_open'] %}
                  <a href="{{ url_for('admin_toggle_topic', topic_id=t['id']) }}">Close Voting</a>
              {% else %}
                  <a href="{{ url_for('admin_toggle_topic', topic_id=t['id']) }}">Open Voting</a>
              {% endif %}
          </td>
      </tr>
      {% endfor %}
  </table>
  <p class="subtle">Owner (and developer) voting link: <code>{{ url_for('vote_topic_selector', _external=True) }}</code></p>
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
        if label:
            cur.execute("INSERT INTO options (topic_id, label) VALUES (?, ?);", (topic_id, label))
            conn.commit()
            flash(("success", "Option added."))
        else:
            flash(("error", "Option label is required."))
        conn.close()
        return redirect(url_for("admin_topic_options", topic_id=topic_id))

    options = cur.execute("SELECT * FROM options WHERE topic_id = ? ORDER BY id;", (topic_id,)).fetchall()
    conn.close()

    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Options for Topic: {{ topic['title'] }}</h1>
  <h3>Add Option</h3>
  <form method="post">
      <label>Option Label:<br><input type="text" name="label" required></label>
      <br>
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
    flash(("success", f"Topic '{topic['title']}' voting is now {'open' if new_state else 'closed'}"))
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
                base_votes_int = int(base_votes)
                if base_votes_int < 0:
                    base_votes_int = 0
            except ValueError:
                base_votes_int = 0

            try:
                proxy_count_int = int(proxy_count)
                if proxy_count_int < 0:
                    proxy_count_int = 0
            except ValueError:
                proxy_count_int = 0

            cur.execute("""
                UPDATE developer_settings
                SET is_active = ?, base_votes = ?, proxy_count = ?, comment = ?
                WHERE id = 1;
            """, (is_active, base_votes_int, proxy_count_int, comment))
            conn.commit()
            flash(("success", "Developer settings updated."))

            # If developer is active, ensure DEVELOPER registration and PIN exist
            if is_active == 1:
                reg_dev = cur.execute("SELECT * FROM registrations WHERE erf = 'DEVELOPER';").fetchone()
                if not reg_dev:
                    otp_dev = generate_otp()
                    cur.execute(
                        "INSERT INTO registrations (erf, proxies, otp) VALUES ('DEVELOPER', 0, ?);",
                        (otp_dev,),
                    )
                    conn.commit()
                    flash(("success", f"Developer login created. ERF: DEVELOPER, PIN: {otp_dev}"))
                else:
                    if not reg_dev["otp"]:
                        otp_dev = generate_otp()
                        cur.execute(
                            "UPDATE registrations SET otp = ?, proxies = 0 WHERE erf = 'DEVELOPER';",
                            (otp_dev,),
                        )
                        conn.commit()
                        flash(("success", f"Developer PIN generated: {otp_dev}"))

        elif form_type == "add_proxy":
            erf = request.form.get("erf", "").strip()
            note = request.form.get("note", "").strip()
            if not erf:
                flash(("error", "ERF is required to add a developer proxy."))
            else:
                owner = cur.execute("SELECT * FROM owners WHERE erf = ?;", (erf,)).fetchone()
                if not owner:
                    flash(("error", f"No owner found for ERF {erf}. Add the owner first."))
                else:
                    try:
                        cur.execute("""
                            INSERT INTO developer_proxies (erf, note) VALUES (?, ?);
                        """, (erf, note))
                        conn.commit()
                        flash(("success", f"ERF {erf} linked as developer proxy."))
                    except sqlite3.IntegrityError:
                        flash(("error", f"ERF {erf} is already linked as a developer proxy."))

        elif form_type == "delete_proxy":
            proxy_id = request.form.get("proxy_id", "").strip()
            try:
                proxy_id_int = int(proxy_id)
                cur.execute("DELETE FROM developer_proxies WHERE id = ?;", (proxy_id_int,))
                conn.commit()
                flash(("success", "Developer proxy removed."))
            except ValueError:
                flash(("error", "Invalid proxy ID."))

        conn.close()
        return redirect(url_for("admin_developer"))

    settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
    proxies = cur.execute("""
        SELECT dp.id, dp.erf, dp.note, o.name
        FROM developer_proxies dp
        LEFT JOIN owners o ON o.erf = dp.erf
        ORDER BY dp.erf;
    """).fetchall()
    developer_reg = cur.execute("SELECT * FROM registrations WHERE erf = 'DEVELOPER';").fetchone()
    conn.close()

    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Developer Settings</h1>
  <p class="subtle">
    Use this section to configure the developer's votes and proxies.
    Any ERF linked as a developer proxy is <strong>blocked</strong> from individual voting and represented by the developer.
  </p>
  <h3>Developer Configuration</h3>
  <form method="post">
      <input type="hidden" name="form_type" value="settings">
      <p>
        <label>
          <input type="checkbox" name="is_active" {% if settings['is_active'] %}checked{% endif %}>
          Developer applicable for this association
        </label>
      </p>
      <p>
        <label>Developer base votes:<br>
        <input type="number" name="base_votes" min="0" value="{{ settings['base_votes'] }}"></label>
      </p>
      <p>
        <label>Developer proxy count (additional votes not tied to specific ERFs):<br>
        <input type="number" name="proxy_count" min="0" value="{{ settings['proxy_count'] }}"></label>
      </p>
      <p>
        <label>Comments on developer votes:<br>
        <textarea name="comment">{{ settings['comment'] or '' }}</textarea></label>
      </p>
      <button type="submit">Save Developer Settings</button>
  </form>

  {% if settings['is_active'] %}
  <hr>
  <h3>Developer Login Details</h3>
  {% if developer_reg and developer_reg['otp'] %}
    <p>ERF / Username: <code>DEVELOPER</code><br>
       PIN: <code>{{ developer_reg['otp'] }}</code></p>
    <p class="subtle">Share this login so the developer can vote directly at the normal voting link.</p>
  {% else %}
    <p class="subtle">Developer is marked applicable, but no login PIN has been generated yet.</p>
  {% endif %}
  {% endif %}

  <hr>

  <h3>Developer Proxies (linked ERFs)</h3>
  <p class="subtle">
    Each ERF linked here is considered represented by the developer and cannot log in to vote individually.
  </p>
  <form method="post">
      <input type="hidden" name="form_type" value="add_proxy">
      <p><label>ERF to link:<br><input type="text" name="erf" required></label></p>
      <p><label>Note / comment (optional):<br><textarea name="note"></textarea></label></p>
      <button type="submit">Add Developer Proxy ERF</button>
  </form>

  <h4>Linked Developer ERFs</h4>
  {% if not proxies %}
    <p class="subtle">No ERFs linked to the developer yet.</p>
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

    settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
    if not settings or not settings["is_active"]:
        conn.close()
        template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Developer Vote</h1>
  <p>Developer is not enabled for this association. Enable it under the Developer tab first.</p>
</div>
""" + BASE_TAIL
        return render_template_string(template)

    topic = cur.execute("SELECT * FROM topics WHERE id = ?;", (topic_id,)).fetchone()
    if not topic:
        conn.close()
        return "Topic not found", 404

    options = cur.execute("SELECT * FROM options WHERE topic_id = ? ORDER BY id;", (topic_id,)).fetchall()
    proxies = cur.execute("SELECT * FROM developer_proxies;").fetchall()

    # total developer weight = base_votes + proxy_count + number of linked ERFs
    base_votes = settings["base_votes"] or 0
    proxy_count = settings["proxy_count"] or 0
    linked_count = len(proxies)
    total_weight = base_votes + proxy_count + linked_count

    existing_vote = cur.execute(
        "SELECT * FROM votes WHERE topic_id = ? AND erf = 'DEVELOPER';",
        (topic_id,)
    ).fetchone()

    if request.method == "POST":
        option_id = request.form.get("option_id", "").strip()
        if not option_id:
            flash(("error", "Please select an option for the developer."))
            conn.close()
            return redirect(url_for("admin_developer_vote", topic_id=topic_id))

        try:
            opt_id_int = int(option_id)
        except ValueError:
            flash(("error", "Invalid option selected."))
            conn.close()
            return redirect(url_for("admin_developer_vote", topic_id=topic_id))

        if total_weight <= 0:
            flash(("error", "Developer has zero total vote weight. Check developer settings."))
            conn.close()
            return redirect(url_for("admin_developer_vote", topic_id=topic_id))

        if existing_vote:
            cur.execute(
                "UPDATE votes SET option_id = ?, weight = ? WHERE id = ?;",
                (opt_id_int, total_weight, existing_vote["id"])
            )
        else:
            cur.execute(
                "INSERT INTO votes (topic_id, erf, option_id, weight) VALUES (?, 'DEVELOPER', ?, ?);",
                (topic_id, opt_id_int, total_weight)
            )
        conn.commit()
        conn.close()
        flash(("success", f"Developer vote recorded for topic '{topic['title']}'."))
        return redirect(url_for("admin_topics"))

    conn.close()

    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Developer Vote (Admin)</h1>
  <p><strong>Topic:</strong> {{ topic['title'] }}</p>
  <p>{{ topic['description'] }}</p>
  <p class="subtle">
    Developer total vote weight for this meeting: <strong>{{ total_weight }}</strong>
    (base votes: {{ base_votes }}, proxies count: {{ proxy_count }}, linked ERFs: {{ linked_count }}).
  </p>
  {% if total_weight <= 0 %}
    <p class="badge">Warning: Developer currently has zero weight. Update settings if needed.</p>
  {% endif %}
  <form method="post">
      <h3>Select option for developer</h3>
      {% for o in options %}
      <p>
          <label>
              <input type="radio" name="option_id" value="{{ o['id'] }}"
                {% if existing_vote and existing_vote['option_id'] == o['id'] %}checked{% endif %}>
              {{ o['label'] }}
          </label>
      </p>
      {% endfor %}
      <button type="submit">Save Developer Vote</button>
  </form>
</div>
""" + BASE_TAIL
    return render_template_string(
        template,
        topic=topic,
        options=options,
        base_votes=base_votes,
        proxy_count=proxy_count,
        linked_count=linked_count,
        total_weight=total_weight,
        existing_vote=existing_vote,
    )


@app.route("/vote/login", methods=["GET", "POST"])
def vote_login():
    if request.method == "POST":
        erf = request.form.get("erf", "").strip()
        otp_input = request.form.get("otp", "").strip().upper()
        if not erf or not otp_input:
            flash(("error", "ERF and PIN are required."))
            return redirect(url_for("vote_login"))

        erf_upper = erf.upper()

        conn = get_db()
        cur = conn.cursor()

        # Developer cannot log in if not enabled
        settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
        if erf_upper == "DEVELOPER":
            if not settings or not settings["is_active"]:
                conn.close()
                flash(("error", "Developer is not enabled for this association."))
                return redirect(url_for("vote_login"))

        # Block ERFs linked to developer
        dev_proxy = cur.execute("SELECT 1 FROM developer_proxies WHERE erf = ?;", (erf_upper,)).fetchone()
        if dev_proxy and erf_upper != "DEVELOPER":
            conn.close()
            flash(("error", "This ERF is linked to the developer and cannot vote individually."))
            return redirect(url_for("vote_login"))

        # Block ERFs linked as owner proxies
        owner_proxy = cur.execute("SELECT 1 FROM owner_proxies WHERE proxy_erf = ?;", (erf_upper,)).fetchone()
        if owner_proxy and erf_upper != "DEVELOPER":
            conn.close()
            flash(("error", "This ERF is represented as a proxy by another owner and cannot vote individually."))
            return redirect(url_for("vote_login"))

        reg = cur.execute("SELECT * FROM registrations WHERE erf = ?;", (erf_upper,)).fetchone()
        conn.close()

        if not reg or not reg["otp"]:
            flash(("error", "Invalid ERF or PIN."))
            return redirect(url_for("vote_login"))

        if reg["otp"].upper() != otp_input:
            flash(("error", "Invalid ERF or PIN."))
            return redirect(url_for("vote_login"))

        session["voter_erf"] = erf_upper
        flash(("success", f"Logged in for voting as ERF {erf_upper}."))
        return redirect(url_for("vote_topic_selector"))

    template = BASE_HEAD_PUBLIC + """
<div class="card">
  <h1>Voting Login</h1>
  <p>Please enter your ERF number and the PIN given to you at registration.</p>
  <form method="post">
      <p><label>ERF Number:<br><input type="text" name="erf" required></label></p>
      <p><label>One-Time PIN:<br><input type="password" name="otp" required></label></p>
      <button type="submit">Login</button>
  </form>
</div>
""" + BASE_TAIL
    return render_template_string(template)


@app.route("/vote/logout")
def vote_logout():
    session.pop("voter_erf", None)
    flash(("success", "You have been logged out from voting."))
    return redirect(url_for("vote_login"))


@app.route("/vote", methods=["GET"])
def vote_topic_selector():
    erf = session.get("voter_erf")
    if not erf:
        return redirect(url_for("vote_login"))
    conn = get_db()
    cur = conn.cursor()
    topics = cur.execute("SELECT * FROM topics WHERE is_open = 1 ORDER BY id DESC;").fetchall()
    conn.close()

    template = BASE_HEAD_PUBLIC + """
<div class="card">
  <h1>Owner Voting</h1>
  <p>Logged in as ERF <strong>{{ voter_erf }}</strong>. <a href="{{ url_for('vote_logout') }}">Logout</a></p>
  {% if not topics %}
      <p>No open voting topics at the moment.</p>
  {% else %}
      <p>Select a topic to vote on:</p>
      <ul>
      {% for t in topics %}
          <li><a href="{{ url_for('vote_topic', topic_id=t['id']) }}">{{ t['title'] }}</a></li>
      {% endfor %}
      </ul>
  {% endif %}
</div>
""" + BASE_TAIL
    return render_template_string(template, topics=topics, voter_erf=erf)


@app.route("/vote/<int:topic_id>", methods=["GET", "POST"])
def vote_topic(topic_id):
    erf = session.get("voter_erf")
    if not erf:
        return redirect(url_for("vote_login"))

    conn = get_db()
    cur = conn.cursor()

    topic = cur.execute("SELECT * FROM topics WHERE id = ?;", (topic_id,)).fetchone()
    if not topic or not topic["is_open"]:
        conn.close()
        template = BASE_HEAD_PUBLIC + "<div class='card'><h1>Voting not available for this topic.</h1></div>" + BASE_TAIL
        return render_template_string(template)

    options = cur.execute("SELECT * FROM options WHERE topic_id = ? ORDER BY id;", (topic_id,)).fetchall()

    if request.method == "POST":
        option_id = request.form.get("option_id", "").strip()

        if not option_id:
            flash(("error", "Please select an option."))
            conn.close()
            return redirect(url_for("vote_topic", topic_id=topic_id))

        reg = cur.execute("SELECT * FROM registrations WHERE erf = ?;", (erf,)).fetchone()
        if not reg:
            flash(("error", f"ERF {erf} is not registered for this meeting."))
            conn.close()
            return redirect(url_for("vote_topic", topic_id=topic_id))

        existing = cur.execute(
            "SELECT * FROM votes WHERE topic_id = ? AND erf = ?;",
            (topic_id, erf)
        ).fetchone()
        if existing:
            flash(("error", "This ERF has already voted on this topic."))
            conn.close()
            return redirect(url_for("vote_topic", topic_id=topic_id))

        try:
            opt_id_int = int(option_id)
        except ValueError:
            flash(("error", "Invalid option selected."))
            conn.close()
            return redirect(url_for("vote_topic", topic_id=topic_id))

        # Special handling for DEVELOPER vote weight
        if erf == "DEVELOPER":
            settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
            proxies_rows = cur.execute("SELECT COUNT(*) AS c FROM developer_proxies;").fetchone()
            linked_count = proxies_rows["c"] if proxies_rows else 0

            base_votes = settings["base_votes"] if settings else 0
            proxy_count = settings["proxy_count"] if settings else 0
            total_weight = (base_votes or 0) + (proxy_count or 0) + linked_count

            if not settings or not settings["is_active"]:
                flash(("error", "Developer is not enabled for this association."))
                conn.close()
                return redirect(url_for("vote_topic", topic_id=topic_id))

            if total_weight <= 0:
                flash(("error", "Developer currently has zero total vote weight. Check developer settings."))
                conn.close()
                return redirect(url_for("vote_topic", topic_id=topic_id))

            weight = total_weight
        else:
            weight = 1 + (reg["proxies"] or 0)

        cur.execute(
            "INSERT INTO votes (topic_id, erf, option_id, weight) VALUES (?, ?, ?, ?);",
            (topic_id, erf, opt_id_int, weight)
        )
        conn.commit()
        conn.close()
        template = BASE_HEAD_PUBLIC + "<div class='card'><h1>Thank you, your vote has been recorded.</h1></div>" + BASE_TAIL
        return render_template_string(template)

    conn.close()
    template = BASE_HEAD_PUBLIC + """
<div class="card">
  <h1>Voting Ballot</h1>
  <p>Logged in as ERF <strong>{{ voter_erf }}</strong>. <a href="{{ url_for('vote_logout') }}">Logout</a></p>
  <h2>{{ topic['title'] }}</h2>
  <p>{{ topic['description'] }}</p>
  <form method="post">
      <h3>Options</h3>
      {% for o in options %}
      <p>
          <label>
              <input type="radio" name="option_id" value="{{ o['id'] }}">
              {{ o['label'] }}
          </label>
      </p>
      {% endfor %}
      <button type="submit">Submit Vote</button>
  </form>
</div>
""" + BASE_TAIL
    return render_template_string(template, topic=topic, options=options, voter_erf=erf)


# ---------- EXPORT PAGES ----------

@app.route("/admin/export")
def admin_export():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))

    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Export Data</h1>
  <p>Export CSV files for auditing and quorum calculations.</p>

  <h3>1. Voting Results</h3>
  <p>Topic, option, and total vote weight for each option.</p>
  <p><a href="{{ url_for('admin_export_votes') }}"><button type="button">Download Voting Results CSV</button></a></p>

  <hr>

  <h3>2. Developer Profile</h3>
  <p>Developer settings and all ERFs linked to the developer.</p>
  <p><a href="{{ url_for('admin_export_developer') }}"><button type="button">Download Developer Profile CSV</button></a></p>

  <hr>

  <h3>3. Registrations & Quorum Data</h3>
  <p>Owners, registrations, proxies, and blocked ERFs to help you calculate if a quorum was reached.</p>
  <p><a href="{{ url_for('admin_export_registrations') }}"><button type="button">Download Registrations CSV</button></a></p>
</div>
""" + BASE_TAIL
    return render_template_string(template)


@app.route("/admin/export/votes")
def admin_export_votes():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()

    rows = cur.execute("""
        SELECT t.id AS topic_id,
               t.title AS topic_title,
               o.label AS option_label,
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

    csv_text = text_buffer.getvalue()
    binary_buffer = BytesIO(csv_text.encode("utf-8"))
    binary_buffer.seek(0)

    return send_file(
        binary_buffer,
        mimetype="text/csv",
        as_attachment=True,
        download_name="hoa_voting_results.csv"
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
        total_weight = base_votes + proxy_count + total_linked
        is_active = settings["is_active"]
        comment = settings["comment"] or ""
    else:
        base_votes = 0
        proxy_count = 0
        total_weight = 0
        is_active = 0
        comment = ""

    conn.close()

    text_buffer = StringIO()
    writer = csv.writer(text_buffer)

    # Header row
    writer.writerow([
        "Section",
        "ERF",
        "Owner Name",
        "Base Votes",
        "Developer Proxy Count",
        "Developer Comment",
        "Developer Active (1/0)",
        "Total Linked ERFs",
        "Total Developer Vote Weight",
        "Proxy Note",
    ])

    # Settings row
    writer.writerow([
        "settings",
        "DEVELOPER",
        "",
        base_votes,
        proxy_count,
        comment,
        is_active,
        total_linked,
        total_weight,
        "",
    ])

    # Proxy rows
    for p in proxies:
        writer.writerow([
            "proxy",
            p["erf"],
            p["name"] or "",
            "",
            "",
            "",
            "",
            "",
            "",
            p["note"] or "",
        ])

    csv_text = text_buffer.getvalue()
    binary_buffer = BytesIO(csv_text.encode("utf-8"))
    binary_buffer.seek(0)

    return send_file(
        binary_buffer,
        mimetype="text/csv",
        as_attachment=True,
        download_name="hoa_developer_profile.csv"
    )


@app.route("/admin/export/registrations")
def admin_export_registrations():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()

    owners = cur.execute("SELECT * FROM owners ORDER BY erf;").fetchall()
    regs = cur.execute("SELECT * FROM registrations;").fetchall()
    regs_by_erf = {r["erf"]: r for r in regs}

    dev_proxies_rows = cur.execute("SELECT erf FROM developer_proxies;").fetchall()
    dev_proxy_erfs = {row["erf"] for row in dev_proxies_rows}

    owner_proxies_rows = cur.execute("SELECT primary_erf, proxy_erf FROM owner_proxies;").fetchall()
    owner_proxy_map = {row["proxy_erf"]: row["primary_erf"] for row in owner_proxies_rows}

    settings = cur.execute("SELECT * FROM developer_settings WHERE id = 1;").fetchone()
    dev_linked_count_row = cur.execute("SELECT COUNT(*) AS c FROM developer_proxies;").fetchone()
    if settings:
        base_votes = settings["base_votes"] or 0
        proxy_count = settings["proxy_count"] or 0
        dev_linked_count = dev_linked_count_row["c"] if dev_linked_count_row else 0
        dev_total_weight = base_votes + proxy_count + dev_linked_count
        dev_active = settings["is_active"]
    else:
        base_votes = 0
        proxy_count = 0
        dev_linked_count = 0
        dev_total_weight = 0
        dev_active = 0

    # Also include DEVELOPER even if not in owners
    has_developer_owner = any(o["erf"] == "DEVELOPER" for o in owners)

    conn.close()

    text_buffer = StringIO()
    writer = csv.writer(text_buffer)
    writer.writerow([
        "ERF",
        "Owner Name",
        "Registered?",
        "Numeric Proxies",
        "Total Vote Weight (if voting individually)",
        "Is Developer",
        "Blocked (Developer/Owner Proxy)?",
        "Blocked By",
    ])

    # Normal owners
    for o in owners:
        erf = o["erf"]
        name = o["name"] or ""
        reg = regs_by_erf.get(erf)
        registered = "Yes" if reg else "No"
        numeric_proxies = reg["proxies"] if reg else 0

        is_dev = "Yes" if erf == "DEVELOPER" else "No"

        blocked = "No"
        blocked_by = ""
        if erf in dev_proxy_erfs:
            blocked = "Yes"
            blocked_by = "Developer"
        elif erf in owner_proxy_map:
            blocked = "Yes"
            blocked_by = f"Owner proxy holder: {owner_proxy_map[erf]}"

        if erf == "DEVELOPER":
            total_weight = dev_total_weight if dev_active else 0
        else:
            if registered and blocked == "No":
                total_weight = 1 + (numeric_proxies or 0)
            else:
                total_weight = 0

        writer.writerow([
            erf,
            name,
            registered,
            numeric_proxies,
            total_weight,
            is_dev,
            blocked,
            blocked_by,
        ])

    # Include DEVELOPER row if not in owners but exists in registrations/settings
    if not has_developer_owner:
        dev_reg = regs_by_erf.get("DEVELOPER")
        registered = "Yes" if dev_reg else "No"
        writer.writerow([
            "DEVELOPER",
            "",
            registered,
            dev_reg["proxies"] if dev_reg else 0,
            dev_total_weight if dev_active else 0,
            "Yes",
            "No",
            "",
        ])

    csv_text = text_buffer.getvalue()
    binary_buffer = BytesIO(csv_text.encode("utf-8"))
    binary_buffer.seek(0)

    return send_file(
        binary_buffer,
        mimetype="text/csv",
        as_attachment=True,
        download_name="hoa_registrations_quorum.csv"
    )


@app.route("/admin/reset", methods=["GET", "POST"])
def admin_reset():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    if request.method == "POST":
        if os.path.exists(DB_NAME):
            os.remove(DB_NAME)
        init_db()
        flash(("success", "All data has been reset. You can now start a new association/meeting."))
        return redirect(url_for("admin_dashboard"))

    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Reset All Data</h1>
  <p><strong>Warning:</strong> This will delete all owners, registrations, developer data, topics, options and votes.</p>
  <form method="post">
      <button type="submit">Yes, reset everything</button>
  </form>
</div>
""" + BASE_TAIL
    return render_template_string(template)


if __name__ == "__main__":
    if not os.path.exists(DB_NAME):
        init_db()
    else:
        init_db()
    app.run(host="0.0.0.0", port=5000, debug=False)
