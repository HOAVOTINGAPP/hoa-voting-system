import os, re, sys

APP = "hoa_voting_app.py"

with open(APP, "r", encoding="utf-8") as f:
    s = f.read()

# 1. Remove any broken previous block
cleaned = re.sub(
    r"# ------------------- START: Scan & QR quick-login additions -------------------.*?# ------------------- END: Scan & QR quick-login additions -------------------",
    "",
    s,
    flags=re.DOTALL
)

# 2. Correct, safe version of the block (NO escaped quotes)
insert_block = """
# ------------------- START: Scan & QR quick-login additions -------------------
from io import BytesIO as _BytesIO

@app.route("/admin/scan_register", methods=["GET", "POST"])
def admin_scan_register():
    if not admin_logged_in():
        return redirect(url_for("admin_login"))
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        scanned = request.form.get("scanned", "").strip().upper()
        if not scanned:
            flash(("error", "No ERF scanned."))
            conn.close()
            return redirect(url_for("admin_scan_register"))

        owner = cur.execute("SELECT * FROM owners WHERE erf = ?;", (scanned,)).fetchone()
        if not owner and scanned != "DEVELOPER":
            flash(("error", f"No owner found for scanned ERF {scanned}"))
            conn.close()
            return redirect(url_for("admin_scan_register"))

        otp = generate_otp()
        cur.execute(
            "INSERT INTO registrations (erf, proxies, otp) VALUES (?, 0, ?) "
            "ON CONFLICT(erf) DO UPDATE SET otp=excluded.otp;",
            (scanned, otp)
        )
        conn.commit()
        conn.close()

        quick_url = url_for("vote_quick", _external=True) + f"?erf={scanned}&otp={otp}"

        template = BASE_HEAD_ADMIN + f"""
<div class='card'>
  <h1>Scanned: {scanned}</h1>
  <p>OTP: <strong>{otp}</strong></p>
  <p>QR code:</p>
  <img src='{{{{ url_for("qr_image", erf="{scanned}") }}}}' alt='QR'>
  <p>Or open: <a href='{quick_url}'>{quick_url}</a></p>
  <a href='{{{{ url_for("admin_registrations") }}}}'>Back</a>
</div>
""" + BASE_TAIL
        return render_template_string(template)

    template = BASE_HEAD_ADMIN + """
<div class='card'>
  <h1>Scan owner ID</h1>
  <form method='post'>
    <label>Scanned ERF:<br><input name='scanned' autofocus></label>
    <button type='submit'>Submit</button>
  </form>
</div>
""" + BASE_TAIL
    return render_template_string(template)

@app.route("/qr/<erf>")
def qr_image(erf):
    conn = get_db()
    cur = conn.cursor()
    erf = erf.strip().upper()
    reg = cur.execute("SELECT otp FROM registrations WHERE erf = ?;", (erf,)).fetchone()
    conn.close()
    if not reg:
        return "Not registered", 404
    otp = reg["otp"]
    url = url_for("vote_quick", _external=True) + f"?erf={erf}&otp={otp}"

    import qrcode
    img = qrcode.make(url)
    buf = _BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/vote/quick")
def vote_quick():
    erf = request.args.get("erf", "").upper().strip()
    otp = request.args.get("otp", "").upper().strip()

    conn = get_db()
    cur = conn.cursor()
    reg = cur.execute("SELECT otp FROM registrations WHERE erf = ?;", (erf,)).fetchone()
    conn.close()

    if not reg or reg["otp"] != otp:
        flash(("error", "Invalid one-time PIN"))
        return redirect(url_for("vote_login"))

    session["voter_erf"] = erf
    return redirect(url_for("vote_topic_selector"))
# ------------------- END: Scan & QR quick-login additions -------------------
"""

# 3. Insert block before app.run or __main__
anchor = re.search(r"if\s+__name__\s*==", cleaned)
if anchor:
    pos = anchor.start()
    final = cleaned[:pos] + insert_block + "\n" + cleaned[pos:]
else:
    final = cleaned + "\n" + insert_block

with open(APP, "w", encoding="utf-8") as f:
    f.write(final)

print("Scan & QR block successfully inserted.")
