import os
import csv
import random
import string
import hashlib
from datetime import datetime, date
from io import StringIO

import psycopg2
from psycopg2.extras import RealDictCursor
from flask import (
    Flask, request, redirect, url_for,
    render_template_string, send_file,
    flash, session, abort
)

# ======================================================
# Configuration (Render + Supabase)
# ======================================================

DATABASE_URL = os.environ["DATABASE_URL"]
SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret")

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ======================================================
# DB helpers (NO GLOBAL CONNECTIONS)
# ======================================================

def get_conn():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )

def set_search_path(cur, schema):
    cur.execute(f"SET search_path TO {schema}, public;")

# ======================================================
# HOA context enforcement (CRITICAL)
# ======================================================

def require_hoa_schema():
    schema = session.get("hoa_schema")
    if not schema:
        abort(403)
    return schema

# ======================================================
# Utilities
# ======================================================

def generate_otp(length=6):
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choice(chars) for _ in range(length))

GENESIS_HASH = "GENESIS"

def compute_vote_hash(prev_hash, erf, topic_id, option_id, weight, ts):
    payload = f"{prev_hash}|{erf}|{topic_id}|{option_id}|{weight}|{ts}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

# ======================================================
# HOA + ADMIN AUTHENTICATION
# ======================================================

def resolve_admin(email, password):
    """
    Legacy-compatible admin auth:
    - Plaintext password comparison
    - HOA user must be enabled
    - HOA must be enabled
    - HOA subscription must not be expired
    Returns schema_name on success, else None
    """
    conn = get_conn()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            u.password,
            u.enabled        AS user_enabled,
            h.schema_name,
            h.enabled        AS hoa_enabled,
            h.subscription_end
        FROM public.hoa_users u
        JOIN public.hoas h ON h.id = u.hoa_id
        WHERE u.email = %s
        """,
        (email,)
    )

    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    if not row["user_enabled"]:
        return None

    if not row["hoa_enabled"]:
        return None

    if row["subscription_end"] < date.today():
        return None

    # Legacy behaviour: plaintext comparison
    if row["password"] != password:
        return None

    return row["schema_name"]

# ======================================================
# Layout Templates
# ======================================================

BASE_HEAD_ADMIN = """
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>HOA AGM Admin</title>
<style>

body {
    font-family: Arial, sans-serif;
    background: #f4f6f8;
    margin: 0;
}

.container {
    max-width: 1100px;
    margin: 30px auto;
    padding: 0 10px;
}

.navbar {
    background: #0f172a;
    padding: 14px 20px;
    border-radius: 10px;
    margin-bottom: 20px;
}

.navbar a {
    color: white;
    text-decoration: none;
    margin-right: 20px;
    font-weight: 500;
}

.navbar a:hover {
    text-decoration: underline;
}

.card {
    background: white;
    padding: 22px;
    border-radius: 10px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
}

.bad {
    color: #dc2626;
    font-weight: bold;
}

.ok {
    color: #16a34a;
    font-weight: bold;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 10px;
}

th, td {
    padding: 10px;
    border-bottom: 1px solid #e5e7eb;
    text-align: left;
}

button, .btn {
    padding: 8px 14px;
    border-radius: 6px;
    border: none;
    background: #2563eb;
    color: white;
    cursor: pointer;
    text-decoration: none;
    display: inline-block;
}

button:hover, .btn:hover {
    background: #1d4ed8;
}

</style>
</head>
<body>

<div class="container">

<div class="navbar">
<a href="/admin">Dashboard</a>
<a href="/admin/owners">Owners</a>
<a href="/admin/owner_proxies">Owner Proxies</a>
<a href="/admin/registrations">Registrations</a>
<a href="/admin/topics">Topics</a>
<a href="/admin/developer">Developer</a>
<a href="/admin/export">Export</a>
<a href="/admin/verify">Verify</a>
<a href="/admin/reset">Reset</a>
<a href="/admin/logout">Logout</a>
</div>
"""

BASE_TAIL = """
</div>
</body>
</html>
"""

# ======================================================
# Session Guards
# ======================================================

def require_admin():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

def require_voter():
    if not session.get("voter_erf"):
        return redirect("/vote/login")

# ======================================================
# Admin Login / Logout
# ======================================================

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()

        schema = resolve_admin(email, password)
        if not schema:
            return render_template_string(
                "<h3>Invalid credentials or HOA inactive</h3>"
            )

        session.clear()
        session["admin_logged_in"] = True
        session["hoa_schema"] = schema

        return redirect("/admin")

    return render_template_string("""
    <h2>Admin Login</h2>
    <form method="post">
      <p><input name="email" placeholder="Email"></p>
      <p><input type="password" name="password" placeholder="Password"></p>
      <button>Login</button>
    </form>
    """)

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin/login")

# ======================================================
# Admin Dashboard
# ======================================================

@app.route("/admin")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    return render_template_string(
        BASE_HEAD_ADMIN + """
<div class="card">
  <h2>HOA AGM Admin Dashboard</h2>
  <p>Public voting link:</p>
  <code>{{ url_for('vote_login', _external=True) }}</code>
</div>
""" + BASE_TAIL
    )

# ======================================================
# OWNERS (CSV UPLOAD / VIEW)
# ======================================================

@app.route("/admin/owners", methods=["GET", "POST"])
def admin_owners():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    if request.method == "POST":
        file = request.files.get("file")
        if file:
            reader = csv.reader(StringIO(file.read().decode("utf-8")))
            for row in reader:
                if not row:
                    continue
                if row[0].strip().lower() == "erf":
                    continue

                erf = row[0].strip().upper()
                name = row[1].strip() if len(row) > 1 else None
                id_number = row[2].strip() if len(row) > 2 else None

                cur.execute(
                    """
                    INSERT INTO owners (erf, name, id_number)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (erf)
                    DO UPDATE SET
                        name = EXCLUDED.name,
                        id_number = EXCLUDED.id_number
                    """,
                    (erf, name, id_number)
                )
            conn.commit()

    owners = cur.execute(
        "SELECT * FROM owners ORDER BY erf"
    ).fetchall()

    conn.close()

    return render_template_string(
        BASE_HEAD_ADMIN + """
<div class="card">
<h2>Owners</h2>
<form method="post" enctype="multipart/form-data">
  <input type="file" name="file">
  <button>Upload CSV</button>
</form>
<table>
<tr><th>ERF</th><th>Name</th><th>ID Number</th></tr>
{% for o in owners %}
<tr>
  <td>{{ o.erf }}</td>
  <td>{{ o.name }}</td>
  <td>{{ o.id_number }}</td>
</tr>
{% endfor %}
</table>
</div>
""" + BASE_TAIL,
        owners=owners
    )

# ======================================================
# REGISTRATIONS & OTP (NEGATIVE-GUARD FIXED)
# ======================================================

@app.route("/admin/registrations", methods=["GET", "POST"])
def admin_registrations():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    message = None

    if request.method == "POST":
        erf = request.form.get("erf", "").strip().upper()
        proxies_raw = request.form.get("proxies", "0")
        try:
            proxies = max(0, int(proxies_raw))
        except ValueError:
            proxies = 0

        # ERF must exist in owners, except DEVELOPER
        if erf != "DEVELOPER":
            owner = cur.execute(
                "SELECT 1 FROM owners WHERE erf=%s",
                (erf,)
            ).fetchone()
            if not owner:
                conn.close()
                return render_template_string(
                    BASE_HEAD_ADMIN + """
<div class="card bad">
ERF not found in owners list.
</div>
""" + BASE_TAIL
                )

        otp = generate_otp()

        cur.execute(
            """
            INSERT INTO registrations (erf, proxies, otp)
            VALUES (%s, %s, %s)
            ON CONFLICT (erf)
            DO UPDATE SET
                proxies = EXCLUDED.proxies,
                otp = EXCLUDED.otp
            """,
            (erf, proxies, otp)
        )
        conn.commit()
        message = f"OTP for {erf}: {otp}"

    rows = cur.execute(
        "SELECT * FROM registrations ORDER BY erf"
    ).fetchall()

    conn.close()

    return render_template_string(
        BASE_HEAD_ADMIN + """
<div class="card">
<h2>Registrations</h2>
{% if message %}
<p class="ok">{{ message }}</p>
{% endif %}
<form method="post">
  <input name="erf" placeholder="ERF">
  <input type="number" name="proxies" value="0" min="0">
  <button>Register</button>
</form>
<table>
<tr><th>ERF</th><th>Numeric Proxies</th><th>OTP</th></tr>
{% for r in rows %}
<tr>
  <td>{{ r.erf }}</td>
  <td>{{ r.proxies }}</td>
  <td>{{ r.otp }}</td>
</tr>
{% endfor %}
</table>
</div>
""" + BASE_TAIL,
        rows=rows,
        message=message
    )

# ======================================================
# PUBLIC VOTING — LOGIN / LOGOUT (HOA ENFORCED)
# ======================================================

@app.route("/vote/login", methods=["GET", "POST"])
def vote_login():
    schema = require_hoa_schema()

    if request.method == "POST":
        erf = request.form.get("erf", "").strip().upper()
        otp = request.form.get("otp", "").strip()

        conn = get_conn()
        cur = conn.cursor()
        set_search_path(cur, schema)

        row = cur.execute(
            """
            SELECT * FROM registrations
            WHERE erf=%s AND otp=%s
            """,
            (erf, otp)
        ).fetchone()

        conn.close()

        if not row:
            return render_template_string(
                BASE_HEAD_PUBLIC + """
<div class="card bad">
Invalid ERF or OTP
</div>
""" + BASE_TAIL
            )

        session["voter_erf"] = erf
        return redirect("/vote")

    return render_template_string(
        BASE_HEAD_PUBLIC + """
<div class="card">
<h2>Voting Login</h2>
<form method="post">
  <p><input name="erf" placeholder="ERF"></p>
  <p><input name="otp" placeholder="OTP"></p>
  <button>Login</button>
</form>
</div>
""" + BASE_TAIL
    )

@app.route("/vote/logout")
def vote_logout():
    session.pop("voter_erf", None)
    return redirect("/vote/login")

# ======================================================
# PUBLIC VOTING — TOPIC LIST
# ======================================================

@app.route("/vote")
def vote_index():
    if not session.get("voter_erf"):
        return redirect("/vote/login")

    schema = require_hoa_schema()

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    topics = cur.execute(
        """
        SELECT * FROM topics
        WHERE is_open = TRUE
        ORDER BY id
        """
    ).fetchall()

    conn.close()

    return render_template_string(
        BASE_HEAD_PUBLIC + """
<div class="card">
<h2>Open Voting Topics</h2>
<ul>
{% for t in topics %}
  <li>
    <a href="/vote/{{ t.id }}">{{ t.title }}</a>
  </li>
{% endfor %}
</ul>
</div>
""" + BASE_TAIL,
        topics=topics
    )

# ======================================================
# OWNER PROXY SYSTEM (ADD / DELETE)
# ======================================================

@app.route("/admin/owner_proxies", methods=["GET", "POST"])
def admin_owner_proxies():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    error = None

    if request.method == "POST":
        primary = request.form.get("primary_erf", "").strip().upper()
        proxy = request.form.get("proxy_erf", "").strip().upper()

        if not primary or not proxy:
            error = "Both ERFs are required"
        elif primary == proxy:
            error = "Cannot proxy an ERF to itself"
        else:
            # Both must exist as owners
            p_owner = cur.execute(
                "SELECT 1 FROM owners WHERE erf=%s",
                (primary,)
            ).fetchone()
            x_owner = cur.execute(
                "SELECT 1 FROM owners WHERE erf=%s",
                (proxy,)
            ).fetchone()

            if not p_owner or not x_owner:
                error = "Both ERFs must exist in owners"
            else:
                # Proxy ERF must not already be an owner proxy
                already_proxy = cur.execute(
                    "SELECT 1 FROM owner_proxies WHERE proxy_erf=%s",
                    (proxy,)
                ).fetchone()

                # Proxy ERF must not be a developer proxy
                dev_proxy = cur.execute(
                    "SELECT 1 FROM developer_proxies WHERE erf=%s",
                    (proxy,)
                ).fetchone()

                # Proxy ERF must not have voted
                voted = cur.execute(
                    "SELECT 1 FROM votes WHERE erf=%s",
                    (proxy,)
                ).fetchone()

                if already_proxy or dev_proxy or voted:
                    error = "Proxy ERF is not eligible"
                else:
                    cur.execute(
                        """
                        INSERT INTO owner_proxies (primary_erf, proxy_erf)
                        VALUES (%s, %s)
                        """,
                        (primary, proxy)
                    )
                    conn.commit()

    proxies = cur.execute(
        "SELECT * FROM owner_proxies ORDER BY primary_erf, proxy_erf"
    ).fetchall()

    conn.close()

    return render_template_string(
        BASE_HEAD_ADMIN + """
<div class="card">
<h2>Owner Proxies</h2>
{% if error %}
<p class="bad">{{ error }}</p>
{% endif %}
<form method="post">
  <input name="primary_erf" placeholder="Primary ERF">
  <input name="proxy_erf" placeholder="Proxy ERF">
  <button>Add Proxy</button>
</form>

<table>
<tr><th>Primary ERF</th><th>Proxy ERF</th><th>Action</th></tr>
{% for p in proxies %}
<tr>
  <td>{{ p.primary_erf }}</td>
  <td>{{ p.proxy_erf }}</td>
  <td>
    <form method="post" action="/admin/owner_proxies/delete" style="display:inline">
      <input type="hidden" name="primary" value="{{ p.primary_erf }}">
      <input type="hidden" name="proxy" value="{{ p.proxy_erf }}">
      <button>Delete</button>
    </form>
  </td>
</tr>
{% endfor %}
</table>
</div>
""" + BASE_TAIL,
        proxies=proxies,
        error=error
    )

@app.route("/admin/owner_proxies/delete", methods=["POST"])
def admin_delete_owner_proxy():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    primary = request.form.get("primary")
    proxy = request.form.get("proxy")

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    cur.execute(
        """
        DELETE FROM owner_proxies
        WHERE primary_erf=%s AND proxy_erf=%s
        """,
        (primary, proxy)
    )

    conn.commit()
    conn.close()

    return redirect("/admin/owner_proxies")

# ======================================================
# DEVELOPER SYSTEM (SETTINGS + PROXIES)
# ======================================================

@app.route("/admin/developer", methods=["GET", "POST"])
def admin_developer():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    settings = cur.execute(
        "SELECT * FROM developer_settings WHERE id=1"
    ).fetchone()

    message = None
    error = None

    if request.method == "POST":
        is_active = request.form.get("is_active") == "on"
        base_votes = int(request.form.get("base_votes", "0") or 0)
        proxy_count = int(request.form.get("proxy_count", "0") or 0)
        comment = request.form.get("comment")

        cur.execute(
            """
            UPDATE developer_settings
            SET is_active=%s,
                base_votes=%s,
                proxy_count=%s,
                comment=%s
            WHERE id=1
            """,
            (is_active, base_votes, proxy_count, comment)
        )

        # Developer registration handling
        if is_active:
            otp = generate_otp()
            cur.execute(
                """
                INSERT INTO registrations (erf, proxies, otp)
                VALUES ('DEVELOPER', 0, %s)
                ON CONFLICT (erf)
                DO UPDATE SET otp=EXCLUDED.otp
                """,
                (otp,)
            )
            message = f"Developer OTP: {otp}"
        else:
            cur.execute(
                "DELETE FROM registrations WHERE erf='DEVELOPER'"
            )

        conn.commit()

        settings = cur.execute(
            "SELECT * FROM developer_settings WHERE id=1"
        ).fetchone()

    dev_proxies = cur.execute(
        "SELECT * FROM developer_proxies ORDER BY erf"
    ).fetchall()

    conn.close()

    return render_template_string(
        BASE_HEAD_ADMIN + """
<div class="card">
<h2>Developer Settings</h2>
{% if message %}
<p class="ok">{{ message }}</p>
{% endif %}
{% if error %}
<p class="bad">{{ error }}</p>
{% endif %}
<form method="post">
  <label>
    <input type="checkbox" name="is_active"
      {% if settings.is_active %}checked{% endif %}>
    Enable Developer Voting
  </label><br><br>
  Base Votes:
  <input type="number" name="base_votes" value="{{ settings.base_votes }}"><br>
  Proxy Count:
  <input type="number" name="proxy_count" value="{{ settings.proxy_count }}"><br>
  Comment:<br>
  <textarea name="comment">{{ settings.comment }}</textarea><br>
  <button>Save</button>
</form>
</div>

<div class="card">
<h3>Developer Proxies</h3>
<form method="post" action="/admin/developer/add-proxy">
  <input name="erf" placeholder="ERF">
  <button>Add Developer Proxy</button>
</form>
<table>
<tr><th>ERF</th></tr>
{% for p in dev_proxies %}
<tr><td>{{ p.erf }}</td></tr>
{% endfor %}
</table>
</div>
""" + BASE_TAIL,
        settings=settings,
        dev_proxies=dev_proxies,
        message=message,
        error=error
    )

@app.route("/admin/developer/add-proxy", methods=["POST"])
def admin_add_developer_proxy():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    erf = request.form.get("erf", "").strip().upper()
    if not erf:
        return redirect("/admin/developer")

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    # Must exist as owner
    owner = cur.execute(
        "SELECT 1 FROM owners WHERE erf=%s",
        (erf,)
    ).fetchone()

    if not owner:
        conn.close()
        return redirect("/admin/developer")

    # Must not be owner proxy
    op = cur.execute(
        "SELECT 1 FROM owner_proxies WHERE proxy_erf=%s",
        (erf,)
    ).fetchone()
    if op:
        conn.close()
        return redirect("/admin/developer")

    # Must not have numeric proxies
    reg = cur.execute(
        "SELECT proxies FROM registrations WHERE erf=%s",
        (erf,)
    ).fetchone()
    if reg and reg["proxies"] > 0:
        conn.close()
        return redirect("/admin/developer")

    # Must not have voted
    voted = cur.execute(
        "SELECT 1 FROM votes WHERE erf=%s",
        (erf,)
    ).fetchone()
    if voted:
        conn.close()
        return redirect("/admin/developer")

    cur.execute(
        """
        INSERT INTO developer_proxies (erf)
        VALUES (%s)
        ON CONFLICT DO NOTHING
        """,
        (erf,)
    )

    conn.commit()
    conn.close()
    return redirect("/admin/developer")

# ======================================================
# VOTE WEIGHT COMPUTATION (LEGACY-CORRECT)
# ======================================================

def compute_vote_weight(cur, erf):
    """
    Computes total vote weight for an ERF according to legacy rules.
    """
    # Developer vote
    if erf == "DEVELOPER":
        settings = cur.execute(
            "SELECT * FROM developer_settings WHERE id=1"
        ).fetchone()
        if not settings or not settings["is_active"]:
            return 0

        proxy_count = cur.execute(
            "SELECT COUNT(*) AS c FROM developer_proxies"
        ).fetchone()["c"]

        return (
            settings["base_votes"]
            + settings["proxy_count"]
            + proxy_count
        )

    # Developer proxies cannot vote
    dev_proxy = cur.execute(
        "SELECT 1 FROM developer_proxies WHERE erf=%s",
        (erf,)
    ).fetchone()
    if dev_proxy:
        return 0

    # Owner proxies cannot vote
    owner_proxy = cur.execute(
        "SELECT 1 FROM owner_proxies WHERE proxy_erf=%s",
        (erf,)
    ).fetchone()
    if owner_proxy:
        return 0

    weight = 1

    # Numeric proxies
    reg = cur.execute(
        "SELECT proxies FROM registrations WHERE erf=%s",
        (erf,)
    ).fetchone()
    if reg:
        weight += reg["proxies"]

    # Incoming owner proxies
    incoming = cur.execute(
        """
        SELECT COUNT(*) AS c
        FROM owner_proxies
        WHERE primary_erf=%s
        """,
        (erf,)
    ).fetchone()

    weight += incoming["c"]
    return weight

# ======================================================
# TOPICS & OPTIONS (ADMIN)
# ======================================================

@app.route("/admin/topics", methods=["GET", "POST"])
def admin_topics():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        if title:
            cur.execute(
                """
                INSERT INTO topics (title, description, is_open)
                VALUES (%s, %s, FALSE)
                """,
                (title, description)
            )
            conn.commit()

    topics = cur.execute(
        "SELECT * FROM topics ORDER BY id DESC"
    ).fetchall()

    conn.close()

    return render_template_string(
        BASE_HEAD_ADMIN + """
<div class="card">
<h2>Topics</h2>
<form method="post">
  <p><input name="title" placeholder="Topic title"></p>
  <p><textarea name="description" placeholder="Description"></textarea></p>
  <button>Create Topic</button>
</form>
<table>
<tr><th>Title</th><th>Status</th><th>Actions</th></tr>
{% for t in topics %}
<tr>
  <td>{{ t.title }}</td>
  <td>{{ "OPEN" if t.is_open else "CLOSED" }}</td>
  <td>
    <a href="/admin/topics/{{ t.id }}/options">Options</a> |
    <a href="/admin/topics/{{ t.id }}/toggle">
      {{ "Close" if t.is_open else "Open" }}
    </a>
  </td>
</tr>
{% endfor %}
</table>
</div>
""" + BASE_TAIL,
        topics=topics
    )

@app.route("/admin/topics/<int:topic_id>/toggle")
def admin_toggle_topic(topic_id):
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    cur.execute(
        "UPDATE topics SET is_open = NOT is_open WHERE id=%s",
        (topic_id,)
    )
    conn.commit()
    conn.close()
    return redirect("/admin/topics")

@app.route("/admin/topics/<int:topic_id>/options", methods=["GET", "POST"])
def admin_topic_options(topic_id):
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    topic = cur.execute(
        "SELECT * FROM topics WHERE id=%s",
        (topic_id,)
    ).fetchone()

    allow_add = not topic["is_open"]

    if request.method == "POST" and allow_add:
        label = request.form.get("label", "").strip()
        if label:
            cur.execute(
                """
                INSERT INTO options (topic_id, label)
                VALUES (%s, %s)
                """,
                (topic_id, label)
            )
            conn.commit()

    options = cur.execute(
        "SELECT * FROM options WHERE topic_id=%s ORDER BY id",
        (topic_id,)
    ).fetchall()

    conn.close()

    return render_template_string(
        BASE_HEAD_ADMIN + """
<div class="card">
<h2>Options for: {{ topic.title }}</h2>
{% if allow_add %}
<form method="post">
  <input name="label" placeholder="Option label">
  <button>Add Option</button>
</form>
{% else %}
<p class="bad">Voting is open. Options are locked.</p>
{% endif %}
<table>
<tr><th>Option</th></tr>
{% for o in options %}
<tr><td>{{ o.label }}</td></tr>
{% endfor %}
</table>
<a href="/admin/topics">Back</a>
</div>
""" + BASE_TAIL,
        topic=topic,
        options=options,
        allow_add=allow_add
    )

# ======================================================
# PUBLIC VOTING — CAST VOTE
# ======================================================

@app.route("/vote/<int:topic_id>", methods=["GET", "POST"])
def vote_topic(topic_id):
    if not session.get("voter_erf"):
        return redirect("/vote/login")

    schema = require_hoa_schema()

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    topic = cur.execute(
        """
        SELECT * FROM topics
        WHERE id=%s AND is_open=TRUE
        """,
        (topic_id,)
    ).fetchone()

    if not topic:
        conn.close()
        abort(404)

    erf = session["voter_erf"]

    # Duplicate vote prevention (legacy behaviour)
    already = cur.execute(
        """
        SELECT 1 FROM votes
        WHERE topic_id=%s AND erf=%s
        """,
        (topic_id, erf)
    ).fetchone()

    if already:
        conn.close()
        return render_template_string(
            BASE_HEAD_PUBLIC + """
<div class="card bad">
You have already voted on this topic.
</div>
""" + BASE_TAIL
        )

    weight = compute_vote_weight(cur, erf)
    if weight <= 0:
        conn.close()
        return render_template_string(
            BASE_HEAD_PUBLIC + """
<div class="card bad">
You are not eligible to vote.
</div>
""" + BASE_TAIL
        )

    options = cur.execute(
        """
        SELECT * FROM options
        WHERE topic_id=%s
        ORDER BY id
        """,
        (topic_id,)
    ).fetchall()

    if request.method == "POST":
        option_id = request.form.get("option")
        if not option_id:
            conn.close()
            return redirect(f"/vote/{topic_id}")

        option_id = int(option_id)

        # Hash chaining (global, deterministic)
        last = cur.execute(
            """
            SELECT vote_hash
            FROM votes
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

        prev_hash = last["vote_hash"] if last else GENESIS_HASH
        ts = datetime.utcnow().isoformat()

        vote_hash = compute_vote_hash(
            prev_hash,
            erf,
            topic_id,
            option_id,
            weight,
            ts
        )

        cur.execute(
            """
            INSERT INTO votes
                (topic_id, erf, option_id,
                 weight, prev_hash, vote_hash, timestamp)
            VALUES (%s,%s,%s,%s,%s,%s,%s)
            """,
            (topic_id, erf, option_id,
             weight, prev_hash, vote_hash, ts)
        )

        conn.commit()
        conn.close()
        return redirect("/vote")

    conn.close()

    return render_template_string(
        BASE_HEAD_PUBLIC + """
<div class="card">
<h2>{{ topic.title }}</h2>
<form method="post">
{% for o in options %}
  <p>
    <label>
      <input type="radio" name="option" value="{{ o.id }}" required>
      {{ o.label }}
    </label>
  </p>
{% endfor %}
<button>Submit Vote</button>
</form>
</div>
""" + BASE_TAIL,
        topic=topic,
        options=options
    )

# ======================================================
# VERIFY CRYPTOGRAPHIC VOTE LEDGER (ADMIN)
# ======================================================

@app.route("/admin/verify")
def admin_verify():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    votes = cur.execute(
        "SELECT * FROM votes ORDER BY id"
    ).fetchall()

    prev_hash = GENESIS_HASH
    tampered = False

    for v in votes:
        expected = compute_vote_hash(
            prev_hash,
            v["erf"],
            v["topic_id"],
            v["option_id"],
            v["weight"],
            v["timestamp"]
        )
        if expected != v["vote_hash"]:
            tampered = True
            break
        prev_hash = v["vote_hash"]

    conn.close()

    return render_template_string(
        BASE_HEAD_ADMIN + """
<div class="card">
<h2>Vote Ledger Verification</h2>
{% if tampered %}
<p class="bad">TAMPER DETECTED — vote chain is invalid.</p>
{% else %}
<p class="ok">OK — vote chain is intact.</p>
{% endif %}
</div>
""" + BASE_TAIL,
        tampered=tampered
    )

# ======================================================
# EXPORTS (CSV)
# ======================================================

@app.route("/admin/export")
def admin_export():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    return render_template_string(
        BASE_HEAD_ADMIN + """
<div class="card">
<h2>Exports</h2>
<ul>
  <li><a href="/admin/export/results">Voting Results</a></li>
  <li><a href="/admin/export/developer">Developer Profile</a></li>
  <li><a href="/admin/export/registrations">Registrations / Quorum</a></li>
</ul>
</div>
""" + BASE_TAIL
    )

@app.route("/admin/export/results")
def export_results():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    rows = cur.execute(
        """
        SELECT
            t.title AS topic,
            o.label AS option,
            SUM(v.weight) AS total_votes
        FROM votes v
        JOIN topics t ON t.id = v.topic_id
        JOIN options o ON o.id = v.option_id
        GROUP BY t.title, o.label
        ORDER BY t.title
        """
    ).fetchall()

    conn.close()

    out = StringIO()
    writer = csv.writer(out)
    writer.writerow(["Topic", "Option", "Total Votes"])
    for r in rows:
        writer.writerow([r["topic"], r["option"], r["total_votes"]])

    return send_file(
        StringIO(out.getvalue()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="voting_results.csv"
    )

@app.route("/admin/export/developer")
def export_developer():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    settings = cur.execute(
        "SELECT * FROM developer_settings WHERE id=1"
    ).fetchone()

    proxies = cur.execute(
        "SELECT erf FROM developer_proxies ORDER BY erf"
    ).fetchall()

    conn.close()

    proxy_list = ",".join([p["erf"] for p in proxies])

    total_weight = (
        settings["base_votes"]
        + settings["proxy_count"]
        + len(proxies)
        if settings["is_active"] else 0
    )

    out = StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "Base Votes",
        "Configured Proxy Count",
        "Actual Proxy ERFs",
        "Total Weight",
        "Comment"
    ])
    writer.writerow([
        settings["base_votes"],
        settings["proxy_count"],
        proxy_list,
        total_weight,
        settings["comment"]
    ])

    return send_file(
        StringIO(out.getvalue()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="developer_profile.csv"
    )

@app.route("/admin/export/registrations")
def export_registrations():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    conn = get_conn()
    cur = conn.cursor()
    set_search_path(cur, schema)

    regs = cur.execute(
        "SELECT erf, proxies FROM registrations ORDER BY erf"
    ).fetchall()

    out = StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "ERF",
        "Numeric Proxies",
        "Eligible",
        "Effective Weight"
    ])

    for r in regs:
        weight = compute_vote_weight(cur, r["erf"])
        eligible = "Y" if weight > 0 else "N"
        writer.writerow([
            r["erf"],
            r["proxies"],
            eligible,
            weight
        ])

    conn.close()

    return send_file(
        StringIO(out.getvalue()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="registrations_quorum.csv"
    )

# ======================================================
# RESET HOA DATA (ADMIN ONLY)
# ======================================================

@app.route("/admin/reset", methods=["GET", "POST"])
def admin_reset():
    if not session.get("admin_logged_in"):
        return redirect("/admin/login")

    schema = require_hoa_schema()

    if request.method == "POST":
        conn = get_conn()
        cur = conn.cursor()
        set_search_path(cur, schema)

        cur.execute("""
            TRUNCATE
                owners,
                registrations,
                owner_proxies,
                developer_proxies,
                topics,
                options,
                votes
            RESTART IDENTITY
        """)

        cur.execute("""
            UPDATE developer_settings
            SET is_active=FALSE,
                base_votes=0,
                proxy_count=0,
                comment=NULL
            WHERE id=1
        """)

        conn.commit()
        conn.close()
        return redirect("/admin")

    return render_template_string(
        BASE_HEAD_ADMIN + """
<div class="card bad">
<h2>RESET HOA DATA</h2>
<p>This will permanently delete all HOA voting data.</p>
<form method="post">
  <button>Confirm Reset</button>
</form>
</div>
""" + BASE_TAIL
    )

# ======================================================
# RENDER / LOCAL STARTUP
# ======================================================

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=False
    )
