import os
import csv
import sqlite3
from io import StringIO, BytesIO
from flask import Flask, request, redirect, url_for, render_template_string, send_file, flash

app = Flask(__name__)
app.secret_key = "change_this_to_any_random_string"

DB_NAME = "hoa_meeting.db"


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


# Admin layout (with navigation)
BASE_HEAD_ADMIN = """<!doctype html>
<html>
<head>
    <title>HOA AGM App - Admin</title>
    <meta charset="utf-8">
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        nav a { margin-right: 10px; }
        .error { color: red; }
        .success { color: green; }
        table, th, td { border: 1px solid #ccc; border-collapse: collapse; padding: 4px; }
        th { background: #f0f0f0; }
    </style>
</head>
<body>
<nav>
    <a href="{{ url_for('admin_dashboard') }}">Admin Home</a>
    <a href="{{ url_for('admin_owners') }}">Owners</a>
    <a href="{{ url_for('admin_registrations') }}">Registrations</a>
    <a href="{{ url_for('admin_topics') }}">Topics & Voting</a>
    <a href="{{ url_for('admin_export') }}">Export Results</a>
    <a href="{{ url_for('admin_reset') }}">Reset All</a>
</nav>
<hr>
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
        body { font-family: Arial, sans-serif; margin: 20px; }
        .error { color: red; }
        .success { color: green; }
        table, th, td { border: 1px solid #ccc; border-collapse: collapse; padding: 4px; }
        th { background: #f0f0f0; }
    </style>
</head>
<body>
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
</body>
</html>
"""


@app.route("/admin")
def admin_dashboard():
    vote_url = url_for('vote_topic_selector', _external=True)
    template = BASE_HEAD_ADMIN + f"""
<h1>HOA AGM Admin Dashboard</h1>
<p>Use the navigation links above to manage owners, registrations, topics, voting, export, and reset.</p>
<p>Voting link for owners (share this URL when a topic is open):<br>
   <code>{vote_url}</code>
</p>
""" + BASE_TAIL
    return render_template_string(template)


@app.route("/admin/owners", methods=["GET", "POST"])
def admin_owners():
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
<h1>Owners</h1>
<h3>Upload Owners CSV</h3>
<p>CSV format: <code>erf,owner_name</code>. You can export from Excel as CSV.</p>
<form method="post" enctype="multipart/form-data">
    <input type="file" name="file" accept=".csv">
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
""" + BASE_TAIL
    return render_template_string(template, owners=owners)


@app.route("/admin/registrations", methods=["GET", "POST"])
def admin_registrations():
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

        cur.execute("""
            INSERT INTO registrations (erf, proxies)
            VALUES (?, ?)
            ON CONFLICT(erf) DO UPDATE SET proxies=excluded.proxies;
        """, (erf, proxies_int))
        conn.commit()
        flash(("success", f"Registered ERF {erf} with {proxies_int} proxies."))
        conn.close()
        return redirect(url_for("admin_registrations"))

    regs = cur.execute("""
        SELECT r.erf, r.proxies, o.name
        FROM registrations r
        LEFT JOIN owners o ON o.erf = r.erf
        ORDER BY r.erf;
    """).fetchall()
    conn.close()

    template = BASE_HEAD_ADMIN + """
<h1>Registrations & Proxies</h1>
<h3>Register Owner / Update Proxies</h3>
<form method="post">
    <label>ERF: <input type="text" name="erf" required></label>
    <label>Proxies: <input type="number" name="proxies" min="0" value="0"></label>
    <button type="submit">Save</button>
</form>
<hr>
<h3>Registered ERFs</h3>
<table>
    <tr><th>ERF</th><th>Owner Name</th><th>Proxies</th><th>Total Vote Weight</th></tr>
    {% for r in regs %}
    <tr>
        <td>{{ r['erf'] }}</td>
        <td>{{ r['name'] or '' }}</td>
        <td>{{ r['proxies'] }}</td>
        <td>{{ 1 + (r['proxies'] or 0) }}</td>
    </tr>
    {% endfor %}
</table>
""" + BASE_TAIL
    return render_template_string(template, regs=regs)


@app.route("/admin/topics", methods=["GET", "POST"])
def admin_topics():
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
<h1>Topics & Voting</h1>
<h3>Create New Topic</h3>
<form method="post">
    <p><label>Title: <input type="text" name="title" required></label></p>
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
<p>Owner voting link: <code>{{ url_for('vote_topic_selector', _external=True) }}</code></p>
""" + BASE_TAIL
    return render_template_string(template, topics=topics)


@app.route("/admin/topic/<int:topic_id>/options", methods=["GET", "POST"])
def admin_topic_options(topic_id):
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
<h1>Options for Topic: {{ topic['title'] }}</h1>
<h3>Add Option</h3>
<form method="post">
    <label>Option Label: <input type="text" name="label" required></label>
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
""" + BASE_TAIL
    return render_template_string(template, topic=topic, options=options)


@app.route("/admin/topic/<int:topic_id>/toggle")
def admin_toggle_topic(topic_id):
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


@app.route("/vote", methods=["GET"])
def vote_topic_selector():
    conn = get_db()
    cur = conn.cursor()
    topics = cur.execute("SELECT * FROM topics WHERE is_open = 1 ORDER BY id DESC;").fetchall()
    conn.close()

    template = BASE_HEAD_PUBLIC + """
<h1>Owner Voting</h1>
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
""" + BASE_TAIL
    return render_template_string(template, topics=topics)


@app.route("/vote/<int:topic_id>", methods=["GET", "POST"])
def vote_topic(topic_id):
    conn = get_db()
    cur = conn.cursor()

    topic = cur.execute("SELECT * FROM topics WHERE id = ?;", (topic_id,)).fetchone()
    if not topic or not topic["is_open"]:
        conn.close()
        template = BASE_HEAD_PUBLIC + "<h1>Voting not available for this topic.</h1>" + BASE_TAIL
        return render_template_string(template)

    options = cur.execute("SELECT * FROM options WHERE topic_id = ? ORDER BY id;", (topic_id,)).fetchall()

    if request.method == "POST":
        erf = request.form.get("erf", "").strip()
        option_id = request.form.get("option_id", "").strip()

        if not erf:
            flash(("error", "ERF is required to vote."))
            conn.close()
            return redirect(url_for("vote_topic", topic_id=topic_id))
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
        template = BASE_HEAD_PUBLIC + "<h1>Thank you, your vote has been recorded.</h1>" + BASE_TAIL
        return render_template_string(template)

    conn.close()
    template = BASE_HEAD_PUBLIC + """
<h1>Voting Ballot</h1>
<h2>{{ topic['title'] }}</h2>
<p>{{ topic['description'] }}</p>
<form method="post">
    <p><label>ERF Number: <input type="text" name="erf" required></label></p>
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
""" + BASE_TAIL
    return render_template_string(template, topic=topic, options=options)


@app.route("/admin/export")
def admin_export():
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
    if request.method == "POST":
        if os.path.exists(DB_NAME):
            os.remove(DB_NAME)
        init_db()
        flash(("success", "All data has been reset. You can now start a new association/meeting."))
        return redirect(url_for("admin_dashboard"))

    template = BASE_HEAD_ADMIN + """
<h1>Reset All Data</h1>
<p><strong>Warning:</strong> This will delete all owners, registrations, topics, options and votes.</p>
<form method="post">
    <button type="submit">Yes, reset everything</button>
</form>
""" + BASE_TAIL
    return render_template_string(template)


if __name__ == "__main__":
    if not os.path.exists(DB_NAME):
        init_db()
    else:
        init_db()
    app.run(host="0.0.0.0", port=5000, debug=True)
