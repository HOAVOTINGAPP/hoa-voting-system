import os
import csv
import psycopg2
from psycopg2.extras import RealDictCursor
import random
import string
from io import StringIO, BytesIO
from flask import Flask, request, redirect, url_for, render_template_string, send_file, flash, session
import qrcode
import hashlib
from datetime import datetime

# ================================
# SUPABASE DATABASE ACCESS LAYER
# ================================

def get_db():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    conn = psycopg2.connect(
        url,
        sslmode="require",
        cursor_factory=RealDictCursor
    )
    return conn

def ensure_schema():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS owners (
            id SERIAL PRIMARY KEY,
            erf TEXT UNIQUE NOT NULL,
            name TEXT,
            id_number TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS registrations (
            id SERIAL PRIMARY KEY,
            erf TEXT UNIQUE NOT NULL,
            proxies INTEGER DEFAULT 0,
            otp TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            is_open INTEGER DEFAULT 0
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS options (
            id SERIAL PRIMARY KEY,
            topic_id INTEGER NOT NULL,
            label TEXT NOT NULL
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS votes (
            id SERIAL PRIMARY KEY,
            topic_id INTEGER,
            erf TEXT,
            option_id INTEGER,
            weight INTEGER,
            prev_hash TEXT,
            vote_hash TEXT,
            timestamp TEXT
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
            id SERIAL PRIMARY KEY,
            erf TEXT UNIQUE,
            note TEXT
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS owner_proxies (
            id SERIAL PRIMARY KEY,
            primary_erf TEXT,
            proxy_erf TEXT UNIQUE
        );
    """)

    cur.execute("""
        INSERT INTO developer_settings (id)
        VALUES (1)
        ON CONFLICT DO NOTHING;
    """)

    conn.commit()
    conn.close()

# ================================
# CRYPTOGRAPHIC VOTE LEDGER
# ================================

def compute_vote_hash(prev_hash, erf, topic_id, option_id, weight, timestamp):
    payload = f"{prev_hash}|{erf}|{topic_id}|{option_id}|{weight}|{timestamp}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

app = Flask(__name__)
app.secret_key = "change_this_secret"
ADMIN_PASSWORD = "hoaadmin"

def verify_vote_chain():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT prev_hash, erf, topic_id, option_id, weight, timestamp, vote_hash
        FROM votes
        ORDER BY id ASC
    """)
    rows = cur.fetchall()

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
# AUTHENTICATION LAYER
# =================================================

def require_admin():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

@app.route("/admin/login", methods=["GET","POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password","").strip()

        if password != ADMIN_PASSWORD:
            return render_template_string("<h3>Invalid password</h3>")

        session.clear()
        session["admin_logged_in"] = True
        ensure_schema()
        return redirect("/admin")

    return render_template_string("""
    <html><body>
    <h2>Admin Login</h2>
    <form method="post">
      <input type="password" name="password" placeholder="Admin Password"><br>
      <button>Login</button>
    </form>
    </body></html>
    """)

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin/login")


def generate_otp(length=6):
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def compute_grand_total(conn=None):
    close_conn = False
    if conn is None:
        conn = get_db()
        close_conn = True
    cur = conn.cursor()

    cur.execute("SELECT erf, proxies FROM registrations;")
    regs_raw = cur.fetchall()

    cur.execute("SELECT erf FROM developer_proxies;")
    dev_proxy_erfs = {row["erf"] for row in cur.fetchall()}

    cur.execute("SELECT primary_erf, proxy_erf FROM owner_proxies;")
    owner_proxies_rows = cur.fetchall()
    owner_proxy_map = {row["proxy_erf"]: row["primary_erf"] for row in owner_proxies_rows}
    primary_link_counts = {}
    for row in owner_proxies_rows:
        primary = row["primary_erf"]
        primary_link_counts[primary] = primary_link_counts.get(primary, 0) + 1

    cur.execute("SELECT * FROM developer_settings WHERE id = 1;")
    settings = cur.fetchone()

    cur.execute("SELECT COUNT(*) AS c FROM developer_proxies;")
    dev_linked_count_row = cur.fetchone()

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
                if row[0].strip().lower() == "erf":
                    continue
                erf = row[0].strip().upper()
                name = row[1].strip() if len(row) > 1 else ""
                id_number = row[2].strip() if len(row) > 2 else ""
                if not erf:
                    continue
                cur.execute("""
                    INSERT INTO owners (erf, name, id_number)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (erf) DO UPDATE
                    SET name=EXCLUDED.name,
                        id_number=EXCLUDED.id_number;
                """, (erf, name, id_number))
                count += 1
            conn.commit()
            flash(f"Owners uploaded/updated: {count}")
        except Exception as e:
            flash(f"Error reading CSV: {e}")
        conn.close()
        return redirect(url_for("admin_owners"))

    cur.execute("SELECT * FROM owners ORDER BY erf;")
    owners = cur.fetchall()
    conn.close()
    template = BASE_HEAD_ADMIN + """
<div class="card">
  <h1>Owners</h1>
  <h3>Upload Owners CSV</h3>
  <form method="post" enctype="multipart/form-data">
    <input type="file" name="file" accept=".csv">
    <button type="submit">Upload</button>
  </form>
  <hr>
  <table>
    <tr><th>ERF</th><th>Name</th><th>ID</th></tr>
    {% for o in owners %}
      <tr>
        <td>{{ o['erf'] }}</td>
        <td>{{ o['name'] }}</td>
        <td>{{ o['id_number'] }}</td>
      </tr>
    {% endfor %}
  </table>
</div>
""" + BASE_TAIL
    return render_template_string(template, owners=owners)


@app.route("/admin/topics", methods=["GET", "POST"])
def admin_topics():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    if request.method == "POST":
        title = request.form.get("title","").strip()
        desc = request.form.get("description","").strip()
        if title:
            cur.execute(
                "INSERT INTO topics (title, description, is_open) VALUES (%s,%s,0)",
                (title, desc)
            )
            conn.commit()
    cur.execute("SELECT * FROM topics ORDER BY id DESC;")
    topics = cur.fetchall()
    conn.close()
    template = BASE_HEAD_ADMIN + """
<div class="card">
<h1>Topics</h1>
<form method="post">
<input name="title" placeholder="Title">
<textarea name="description"></textarea>
<button>Create</button>
</form>
<table>
<tr><th>ID</th><th>Title</th><th>Status</th><th>Toggle</th></tr>
{% for t in topics %}
<tr>
<td>{{t['id']}}</td>
<td>{{t['title']}}</td>
<td>{{'Open' if t['is_open'] else 'Closed'}}</td>
<td><a href="{{url_for('admin_toggle_topic',topic_id=t['id'])}}">Toggle</a></td>
</tr>
{% endfor %}
</table>
</div>
""" + BASE_TAIL
    return render_template_string(template, topics=topics)


@app.route("/admin/topic/<int:topic_id>/toggle")
def admin_toggle_topic(topic_id):
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT is_open FROM topics WHERE id=%s", (topic_id,))
    row = cur.fetchone()
    new_state = 0 if row["is_open"] else 1
    cur.execute("UPDATE topics SET is_open=%s WHERE id=%s", (new_state,topic_id))
    conn.commit()
    conn.close()
    return redirect(url_for("admin_topics"))
# ---------- PUBLIC VOTING ----------

@app.route("/vote/login", methods=["GET","POST"])
def vote_login():
    if request.method == "POST":
        erf = request.form.get("erf","").strip().upper()
        otp = request.form.get("otp","").strip().upper()
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM registrations WHERE erf=%s",(erf,))
        reg = cur.fetchone()
        conn.close()
        if not reg or reg["otp"] != otp:
            flash("Invalid login")
            return redirect(url_for("vote_login"))
        session["voter_erf"] = erf
        return redirect(url_for("vote_topic_selector"))
    return render_template_string(BASE_HEAD_PUBLIC + """
    <div class="card">
    <h1>Voting Login</h1>
    <form method="post">
    <input name="erf" placeholder="ERF"><br>
    <input name="otp" placeholder="OTP"><br>
    <button>Login</button>
    </form>
    </div>
    """ + BASE_TAIL)


@app.route("/vote")
def vote_topic_selector():
    erf = session.get("voter_erf")
    if not erf:
        return redirect(url_for("vote_login"))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM topics WHERE is_open=1 ORDER BY id DESC")
    topics = cur.fetchall()
    conn.close()
    return render_template_string(BASE_HEAD_PUBLIC + """
    <div class="card">
    <h1>Select Topic</h1>
    <ul>
    {% for t in topics %}
    <li><a href="{{url_for('vote_topic',topic_id=t['id'])}}">{{t['title']}}</a></li>
    {% endfor %}
    </ul>
    </div>
    """ + BASE_TAIL, topics=topics)


@app.route("/vote/<int:topic_id>", methods=["GET","POST"])
def vote_topic(topic_id):
    erf = session.get("voter_erf")
    if not erf:
        return redirect(url_for("vote_login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM topics WHERE id=%s AND is_open=1",(topic_id,))
    topic = cur.fetchone()
    if not topic:
        conn.close()
        flash("Topic closed")
        return redirect("/vote")

    cur.execute("SELECT * FROM options WHERE topic_id=%s",(topic_id,))
    options = cur.fetchall()

    if request.method=="POST":
        option_id = int(request.form.get("option_id"))
        cur.execute("SELECT * FROM registrations WHERE erf=%s",(erf,))
        reg = cur.fetchone()
        weight = 1 + (reg["proxies"] or 0)

        cur.execute("""
        SELECT vote_hash FROM votes
        WHERE topic_id=%s ORDER BY id DESC LIMIT 1
        """,(topic_id,))
        prev = cur.fetchone()
        prev_hash = prev["vote_hash"] if prev else "GENESIS"
        timestamp = datetime.utcnow().isoformat()
        vote_hash = compute_vote_hash(prev_hash, erf, topic_id, option_id, weight, timestamp)

        cur.execute("""
        INSERT INTO votes
        (topic_id,erf,option_id,weight,prev_hash,vote_hash,timestamp)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
        """,(topic_id,erf,option_id,weight,prev_hash,vote_hash,timestamp))

        conn.commit()
        conn.close()
        return render_template_string(BASE_HEAD_PUBLIC + "<h1>Vote recorded</h1>" + BASE_TAIL)

    conn.close()
    return render_template_string(BASE_HEAD_PUBLIC + """
    <div class="card">
    <h1>{{topic['title']}}</h1>
    <form method="post">
    {% for o in options %}
    <p><input type="radio" name="option_id" value="{{o['id']}}" required> {{o['label']}}</p>
    {% endfor %}
    <button>Submit</button>
    </form>
    </div>
    """ + BASE_TAIL, topic=topic, options=options)


# ---------- VERIFY LEDGER ----------

@app.route("/admin/verify")
def admin_verify_chain():
    ok = verify_vote_chain()
    return "VALID" if ok else "TAMPERED"


# ---------- START ----------

import os
if __name__ == "__main__":
    port = int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0", port=port, debug=False)
