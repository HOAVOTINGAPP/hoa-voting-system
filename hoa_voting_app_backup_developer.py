import os
import csv
import sqlite3
import random
import string
from io import StringIO, BytesIO
from flask import Flask, request, redirect, url_for, render_template_string, send_file, flash, session

app = Flask(__name__)
app.secret_key = "a_long_random_string_just_for_this_app_2025_!!"

DB_NAME = "hoa_meeting.db"
ADMIN_PASSWORD = "123ADMINHOA456"


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
            proxies INTEGER DEFAULT 0
        );
    """)

    # ensure otp column exists
    try:
        cur.execute("ALTER TABLE registrations ADD COLUMN otp TEXT;")
    except sqlite3.OperationalError:
        pass

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
    </style>
</head>
<body>
<div class="shell">
<nav>
    <a href="{{ url_for('admin_dashboard') }}">Admin Home</a>
    <a href="{{ url_for('admin_owners') }}">Owners</a>
    <a href="{{ url_for('admin_registrations') }}">Registrations</a>
    <a href="{{ url_for('admin_topics') }}">Topics & Voting</a>
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
  <p>Use the navigation links above to manage owners, registrations, topics, voting, export, and reset.</p>
  <p class="subtle">Voting link for owners (share this URL when a topic is open):<br>
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
        if not owner:
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
        flash(("success", f"Registered ERF {erf} with {proxies_int} proxies. One-time PIN: {otp}"))
        conn.close()
        return redirect(url_for("admin_registrations"))

    regs = cur.execute("""
        SELECT r.erf, r.proxies, r.otp, o.name
        FROM registrations r
        LEFT JOIN owners o ON o.erf = r.erf
        ORDER BY r.erf;
    """).fetchall()
    conn.close()

    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Registrations & Proxies</h1>
  <h3>Register Owner / Update Proxies</h3>
  <form method="post">
      <p><label>ERF:<br><input type="text" name="erf" required></label></p>
      <p><label>Proxies:<br><input type="number" name="proxies" min="0" value="0"></label></p>
      <button type="submit">Save</button>
  </form>
  <hr>
  <h3>Registered ERFs</h3>
  <p class="subtle">Give each owner their ERF and PIN to access the voting portal.</p>
  <table>
      <tr><th>ERF</th><th>Owner Name</th><th>Proxies</th><th>Total Vote Weight</th><th>One-Time PIN</th></tr>
      {% for r in regs %}
      <tr>
          <td>{{ r['erf'] }}</td>
          <td>{{ r['name'] or '' }}</td>
          <td>{{ r['proxies'] }}</td>
          <td>{{ 1 + (r['proxies'] or 0) }}</td>
          <td><code>{{ r['otp'] or '' }}</code></td>
      </tr>
      {% endfor %}
  </table>
</div>
""" + BASE_TAIL
    return render_template_string(template, regs=regs)


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
      <tr><th>ID</th><th>Title</th><th>Open?</th><th>Options</th><th>Actions</th></tr>
      {% for t in topics %}
      <tr>
          <td>{{ t['id'] }}</td>
          <td>{{ t['title'] }}</td>
          <td>{{ 'Yes' if t['is_open'] else 'No' }}</td>
          <td><a href="{{ url_for('admin_topic_options', topic_id=t['id']) }}">Manage Options</a></td>
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
  <p class="subtle">Owner voting link: <code>{{ url_for('vote_topic_selector', _external=True) }}</code></p>
</div>
""" + BASE_TAIL
    return render_template_string(template, topics=topics)


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


@app.route("/vote/login", methods=["GET", "POST"])
def vote_login():
    if request.method == "POST":
        erf = request.form.get("erf", "").strip()
        otp_input = request.form.get("otp", "").strip().upper()
        if not erf or not otp_input:
            flash(("error", "ERF and PIN are required."))
            return redirect(url_for("vote_login"))

        conn = get_db()
        cur = conn.cursor()
        reg = cur.execute("SELECT * FROM registrations WHERE erf = ?;", (erf,)).fetchone()
        conn.close()
        if not reg or not reg["otp"]:
            flash(("error", "Invalid ERF or PIN."))
            return redirect(url_for("vote_login"))

        if reg["otp"].upper() != otp_input:
            flash(("error", "Invalid ERF or PIN."))
            return redirect(url_for("vote_login"))

        session["voter_erf"] = erf
        flash(("success", f"Logged in for voting as ERF {erf}."))
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


@app.route("/admin/export")
def admin_export():
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
  <p><strong>Warning:</strong> This will delete all owners, registrations, topics, options and votes.</p>
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
