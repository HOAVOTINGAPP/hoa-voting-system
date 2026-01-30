import sys, io, os

APP_PATH = "hoa_voting_app.py"
BACKUP_PATH = "hoa_voting_app_backup_before_scan_qr_insert_py.py"

if not os.path.exists(APP_PATH):
    print("Error: file not found:", APP_PATH)
    sys.exit(1)

# read original
with open(APP_PATH, "r", encoding="utf-8") as f:
    s = f.read()

# backup
with open(BACKUP_PATH, "w", encoding="utf-8") as f:
    f.write(s)
print("Backup written to", BACKUP_PATH)

# if block already present, do nothing
if "Scan & QR quick-login additions" in s:
    print("Scan & QR block already present. No changes made.")
    sys.exit(0)

needle = 'if __name__ == "__main__":'
idx = s.find(needle)
if idx == -1:
    print("Could not find entrypoint line:", needle)
    sys.exit(2)

insert = r"""
# ------------------- START: Scan & QR quick-login additions -------------------
from io import BytesIO as _BytesIO
# Note: qrcode imported locally inside function to avoid top-level changes

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

        # allow DEVELOPER too
        owner = cur.execute("SELECT * FROM owners WHERE erf = ?;", (scanned,)).fetchone()
        if not owner and scanned != "DEVELOPER":
            flash(("error", f"No owner found for scanned ERF {scanned}. Please upload owners or type ERF manually."))
            conn.close()
            return redirect(url_for("admin_scan_register"))

        # register (create or update) and generate OTP
        otp = generate_otp()
        cur.execute(\"\"\"
            INSERT INTO registrations (erf, proxies, otp)
            VALUES (?, 0, ?)
            ON CONFLICT(erf) DO UPDATE SET otp=excluded.otp;
        \"\"\", (scanned, otp))
        conn.commit()

        # prepare quick login URL (this will be encoded into QR)
        quick_url = url_for("vote_quick", _external=True) + f"?erf={scanned}&otp={otp}"
        conn.close()

        # render a small page showing QR, otp, and link
        template = BASE_HEAD_ADMIN + f\"\"\"
<div class="card">
  <h1>Scanned: {scanned}</h1>
  <p class="subtle">One-time PIN: <strong><code>{otp}</code></strong></p>
  <p class="subtle">Scan this QR with the owner's phone to open the voting portal (auto login):</p>
  <p><img src="{{{{ url_for('qr_image', erf='{scanned}') }}}}" alt="QR for {scanned}"></p>
  <p class="subtle">Or open this link on the phone: <br><a href="{quick_url}">{quick_url}</a></p>
  <p><a href="{{{{ url_for('admin_registrations') }}}}">Back to Registrations</a></p>
</div>
\"\"\" + BASE_TAIL
        return render_template_string(template)

    # GET: show scan page
    conn.close()
    template = BASE_HEAD_ADMIN + \"\"\"
<div class="card">
  <h1>Scan owner ID</h1>
  <p class="subtle">Focus the scanner and scan the ERF (or type it). The scanner should send the ERF and an Enter key (most do).</p>
  <form method="post" id="scan-form">
      <p><label>Scanned ERF:<br><input type="text" name="scanned" id="scanned" autofocus autocomplete="off"></label></p>
      <button type="submit">Submit</button>
  </form>
  <p class="subtle">Tip: place a barcode/ID scanner cursor over the input so each scan auto-submits.</p>
</div>

<script>
document.addEventListener('DOMContentLoaded', function(){
    const input = document.getElementById('scanned');
    const form = document.getElementById('scan-form');

    // If scanner sends input + Enter, the form will submit normally.
    // Add a tiny helper: when field loses focus, refocus so next scan is captured.
    input.addEventListener('blur', function(){ setTimeout(()=>input.focus(), 50); });

    // Optional: some scanners do not send Enter; detect quick paste and auto-submit
    let lastTime = 0, buffer = '';
    input.addEventListener('input', function(e){
        const now = Date.now();
        // if characters are arriving quickly, buffer them; if pause > 100ms, assume done
        if (now - lastTime < 80) {
            buffer += e.data || '';
        } else {
            buffer = input.value;
        }
        lastTime = now;
        // If length looks like ERF (>=2) we wait for Enter; otherwise do nothing.
    });
});
</script>
\"\"\" + BASE_TAIL
        return render_template_string(template)

@app.route("/qr/<erf>")
def qr_image(erf):
    # Serve PNG QR of quick login URL for the given ERF.
    # It will point to /vote/quick?erf=...&otp=...
    # If registration exists, use its OTP; otherwise return 404.
    conn = get_db()
    cur = conn.cursor()
    erf_up = erf.strip().upper()
    reg = cur.execute("SELECT * FROM registrations WHERE erf = ?;", (erf_up,)).fetchone()
    if not reg or not reg["otp"]:
        conn.close()
        return "No registration/OTP for that ERF", 404
    otp = reg["otp"]
    quick = url_for("vote_quick", _external=True) + f"?erf={erf_up}&otp={otp}"
    conn.close()
    # generate QR
    import qrcode
    from io import BytesIO
    img = qrcode.make(quick)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png")

@app.route("/vote/quick")
def vote_quick():
    # Quick login via QR: ?erf=...&otp=...
    erf = request.args.get("erf", "").strip().upper()
    otp = request.args.get("otp", "").strip().upper()
    if not erf or not otp:
        flash(("error", "Missing ERF or PIN."))
        return redirect(url_for("vote_login"))

    conn = get_db()
    cur = conn.cursor()
    # Ensure not blocked by developer/owner proxies
    dev_proxy = cur.execute("SELECT 1 FROM developer_proxies WHERE erf = ?;", (erf,)).fetchone()
    owner_block = cur.execute("SELECT 1 FROM owner_proxies WHERE proxy_erf = ?;", (erf,)).fetchone()
    if dev_proxy and erf != "DEVELOPER":
        conn.close()
        flash(("error", "This ERF is linked to the developer and cannot vote individually."))
        return redirect(url_for("vote_login"))
    if owner_block and erf != "DEVELOPER":
        conn.close()
        flash(("error", "This ERF is represented by another owner and cannot vote individually."))
        return redirect(url_for("vote_login"))

    reg = cur.execute("SELECT * FROM registrations WHERE erf = ?;", (erf,)).fetchone()
    conn.close()
    if not reg or not reg["otp"] or reg["otp"].upper() != otp:
        flash(("error", "Invalid or expired PIN."))
        return redirect(url_for("vote_login"))

    # Log the user in for voting (session) and redirect to voting lobby
    session["voter_erf"] = erf
    return redirect(url_for("vote_topic_selector"))
# ------------------- END: Scan & QR quick-login additions -------------------
"""

s_new = s[:idx] + insert + s[idx:]
with open(APP_PATH, "w", encoding="utf-8") as f:
    f.write(s_new)

print("Inserted scan/QR block into", APP_PATH)
