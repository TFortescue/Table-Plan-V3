import hashlib
import json
import os
import pickle
import re
import tempfile
import uuid
from html import escape

from flask import Flask, jsonify, redirect, request, send_file, session, url_for
from flask.sessions import SessionInterface, SessionMixin
from werkzeug.datastructures import CallbackDict
from werkzeug.utils import secure_filename
import io

import pdfs
import planner as pl


# ── Server-side sessions ──────────────────────────────────────────────────────
# Flask's default session is a 4 KB signed cookie, too small for a seating plan.
# Keep the data on disk and only a random session id in the cookie.
class _DiskSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid=None, new=False):
        def on_update(self):
            self.modified = True
        super().__init__(initial or {}, on_update)
        self.sid = sid
        self.new = new
        self.modified = False


class DiskSessionInterface(SessionInterface):
    def __init__(self, directory):
        self.directory = directory
        os.makedirs(directory, exist_ok=True)

    def _path(self, sid):
        safe = "".join(ch for ch in sid if ch in "0123456789abcdef")
        return os.path.join(self.directory, f"sess_{safe}.pkl")

    def open_session(self, app, request):
        sid = request.cookies.get(self.get_cookie_name(app))
        if sid:
            try:
                with open(self._path(sid), "rb") as f:
                    return _DiskSession(pickle.load(f), sid=sid)
            except (OSError, pickle.PickleError, EOFError):
                pass
        return _DiskSession(sid=uuid.uuid4().hex, new=True)

    def save_session(self, app, session, response):
        name = self.get_cookie_name(app)
        domain, path = self.get_cookie_domain(app), self.get_cookie_path(app)
        if not session:
            if session.modified:
                try:
                    os.remove(self._path(session.sid))
                except OSError:
                    pass
                response.delete_cookie(name, domain=domain, path=path)
            return
        if session.modified or session.new:
            tmp = self._path(session.sid) + ".tmp"
            with open(tmp, "wb") as f:
                pickle.dump(dict(session), f)
            os.replace(tmp, self._path(session.sid))
        response.set_cookie(name, session.sid, httponly=True, samesite="Lax",
                            secure=self.get_cookie_secure(app), domain=domain, path=path)


app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-me-in-production")
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
app.session_interface = DiskSessionInterface(
    os.environ.get("SESSION_DIR", os.path.join(tempfile.gettempdir(), "table_planner_sessions")))
UPLOAD_FOLDER = os.environ.get("UPLOAD_DIR", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _asset_version(*names):
    h = hashlib.md5()
    for n in names:
        with open(os.path.join(app.static_folder, n), "rb") as f:
            h.update(f.read())
    return h.hexdigest()[:8]


ASSET_V = _asset_version("app.css", "results.js")


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_plan():
    return session.get("plan")


def save_plan(plan):
    session["plan"] = plan  # reassign so the session notices nested changes


def suggest_table_sizes(n, target=10, max_size=12):
    """As few tables as possible (about `target` each, never more than
    `max_size`), sized evenly: 21 -> [11, 10], 25 -> [9, 8, 8]."""
    if n <= 0:
        return []
    tables = max(1, -(-n // max_size), round(n / target))
    base, extra = divmod(n, tables)
    return [base + 1] * extra + [base] * (tables - extra)


STEPS = [(1, "Upload", "/"), (2, "Guests", "/attendees"), (3, "Tables", "/configure_tables"), (4, "Seating", "/results")]


def page(title, body, step=None, wide=False, scripts=""):
    bar = ""
    if step:
        parts = []
        for i, (n, label, href) in enumerate(STEPS):
            cls = "active" if step == n else ("done" if step > n else "")
            inner = f'<span class="step-num">{n}</span>{label}'
            parts.append(f'<a class="step-item {cls}" href="{href}">{inner}</a>' if step > n
                         else f'<span class="step-item {cls}">{inner}</span>')
        bar = '<div class="step-bar">' + '<span class="step-sep">›</span>'.join(parts) + "</div>"
    nav = "".join(f'<a href="{href}">{label}</a>' for _, label, href in STEPS)
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#1a1410">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>{escape(title)} — Table Planner</title>
<link rel="stylesheet" href="/static/app.css?v={ASSET_V}">
</head><body>
<header class="site-header"><a href="/" class="logo">⬡ Table Planner</a><nav>{nav}</nav></header>
{bar}
<div class="{'page-wide' if wide else 'page'}">{body}</div>
{scripts}
</body></html>"""


def alerts(msgs, kind):
    return "".join(f'<div class="alert alert-{kind}">{escape(m)}</div>' for m in msgs)


def api_error(msg, code=400):
    return jsonify({"error": msg}), code


def state_payload(plan):
    return {
        "plan": pl.export_plan(plan),
        "issues": {m: pl.meal_issues(plan, m) for m in plan["meals"]},
    }


# ── Step 1: upload ────────────────────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def upload_file():
    errors = []
    if request.method == "POST":
        f = request.files.get("csv_file")
        event = " ".join(request.form.get("event", "").split())[:80]
        if not f or not f.filename:
            errors.append("Please choose a file.")
        else:
            raw = f.read()
            if f.filename.lower().endswith(".json") or raw.lstrip()[:1] == b"{":
                try:
                    plan = pl.load_plan(json.loads(raw.decode("utf-8-sig")))
                    if event:
                        plan["event"] = event
                    save_plan(plan)
                    return redirect(url_for("results"))
                except (ValueError, pl.PlanError) as e:
                    errors.append(str(e) if isinstance(e, pl.PlanError) else "That plan file couldn't be read.")
            else:
                path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex[:12]}_{secure_filename(f.filename) or 'guests.csv'}")
                with open(path, "wb") as out:
                    out.write(raw)
                default_event = re.sub(r"[_]+", " ", os.path.splitext(f.filename)[0]).strip()
                plan, errs = pl.plan_from_csv(path, event or default_event)
                try:
                    os.remove(path)  # parsed into the session; don't keep guest lists on disk
                except OSError:
                    pass
                if errs:
                    errors.extend(errs)
                else:
                    save_plan(plan)
                    return redirect(url_for("attendees"))

    body = f"""
<h1>Seating Plan Generator</h1>
<p class="subtitle">Upload a guest list, or open a plan you saved earlier.
<a href="/static/Example_Plan.csv" style="color:var(--gold)">Example CSV</a> ·
<a href="/static/Blank_Plan.csv" style="color:var(--gold)">Blank template</a></p>
{alerts(errors, "error")}
<div class="card resume" id="resume" hidden>
  <h3>Pick up where you left off</h3>
  <p class="text-muted" id="resume-text"></p>
  <button class="btn btn-primary mt1" id="resume-btn" type="button">Resume plan →</button>
</div>
<div class="card mt2">
  <form method="post" enctype="multipart/form-data">
    <div class="form-group">
      <label for="event">Event name (optional)</label>
      <input type="text" id="event" name="event" placeholder="e.g. Shoot Weekend 31st" maxlength="80">
    </div>
    <div class="drop-zone" id="drop-zone">
      <div class="icon">📋</div>
      <p><strong>Choose a guest CSV or a saved plan</strong> or drag it here</p>
      <p class="mt1" id="file-label">.csv or .json</p>
    </div>
    <input type="file" name="csv_file" id="csv-input" accept=".csv,.json,text/csv,application/json">
    <button type="submit" class="btn btn-primary" style="width:100%">Continue →</button>
  </form>
</div>
<div class="card mt2">
  <h3>CSV format</h3>
  <code style="display:block;background:var(--cream);padding:.75rem;border-radius:4px;font-size:.82rem;margin-top:.75rem;overflow-x:auto">name, sex, group, relations, preferred people, [Meal 1], [Meal 2], …</code>
  <p class="text-muted mt2"><strong>sex</strong>: male/female (or M/F). <strong>group</strong> (optional): family or party, kept spread out.
  <strong>relations</strong>: people they must <em>not</em> sit next to. <strong>preferred people</strong>: people they'd like to sit next to.
  Meal columns: <strong>Yes</strong> or <strong>No</strong>, in the order the meals happen.</p>
</div>
<script>
(function() {{
  const dz = document.getElementById('drop-zone'), inp = document.getElementById('csv-input');
  const label = f => document.getElementById('file-label').textContent = '✓ ' + f.name;
  dz.addEventListener('click', () => inp.click());
  inp.addEventListener('change', () => inp.files[0] && label(inp.files[0]));
  dz.addEventListener('dragover', e => {{ e.preventDefault(); dz.classList.add('drag-over'); }});
  dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));
  dz.addEventListener('drop', e => {{
    e.preventDefault(); dz.classList.remove('drag-over');
    const f = e.dataTransfer.files[0]; if (!f) return;
    const dt = new DataTransfer(); dt.items.add(f); inp.files = dt.files; label(f);
  }});
  let saved = null;
  try {{ saved = JSON.parse(localStorage.getItem('tableplanner:plan') || 'null'); }} catch (e) {{}}
  if (saved && saved.plan && saved.plan.meals) {{
    const p = saved.plan, n = (p.people || []).length;
    document.getElementById('resume-text').textContent =
      `“${{p.event}}” · ${{n}} guests · ${{p.meals.length}} meals · last changed ${{saved.at || p.saved_at || ''}} on this device`;
    document.getElementById('resume').hidden = false;
    document.getElementById('resume-btn').addEventListener('click', async () => {{
      const r = await fetch('/api/load_plan', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body: JSON.stringify(p)}});
      if (r.ok) location.href = '/results'; else alert('Sorry, that saved plan could not be opened.');
    }});
  }}
}})();
</script>"""
    return page("Upload", body, step=1)


# ── Step 2: guests ────────────────────────────────────────────────────────────
@app.route("/attendees", methods=["GET", "POST"])
def attendees():
    plan = get_plan()
    if not plan:
        return redirect(url_for("upload_file"))
    ok, errors = [], []
    if request.method == "POST":
        try:
            if request.form.get("action") == "remove":
                name = request.form.get("name", "")
                pl.remove_guest(plan, name)
                ok.append(f"Removed {name}.")
            else:
                split = lambda s: [x.strip() for x in s.split(",") if x.strip()]
                pl.add_guest(plan, request.form.get("name", ""), request.form.get("sex", ""),
                             request.form.getlist("meals"),
                             split(request.form.get("relations", "")), split(request.form.get("preferred", "")))
                plan["people"][-1]["group"] = request.form.get("group", "").strip()
                ok.append(f"Added {plan['people'][-1]['name']}.")
            save_plan(plan)
        except pl.PlanError as e:
            errors.append(str(e))

    meals = plan["meals"]
    stats = ""
    for m in meals:
        names = pl.attendees(plan, m)
        males = sum(1 for p in plan["people"] if m in p["meals"] and p["sex"] == "male")
        stats += f"""<div class="stat-box"><div class="stat-num">{len(names)}</div>
          <div class="stat-label">{escape(m)}</div>
          <div class="text-muted" style="font-size:.75rem;margin-top:.25rem">{males}M · {len(names) - males}F</div></div>"""
    rows = ""
    for p in sorted(plan["people"], key=lambda p: p["name"].lower()):
        badges = " ".join(f'<span class="badge" style="background:var(--cream);color:var(--muted)">{escape(m)}</span>' for m in p["meals"]) or "—"
        rel = escape(", ".join(p["relations"])) or "—"
        rows += f"""<tr><td><strong>{escape(p['name'])}</strong></td>
          <td><span class="badge badge-{p['sex']}">{p['sex'][0].upper()}</span></td>
          <td>{escape(p.get('group') or '—')}</td><td class="text-muted">{rel}</td><td>{badges}</td>
          <td><form method="post" onsubmit="return confirm('Remove this guest from every meal?')">
            <input type="hidden" name="action" value="remove"><input type="hidden" name="name" value="{escape(p['name'])}">
            <button class="btn btn-sm btn-ghost" type="submit" aria-label="Remove">✕</button></form></td></tr>"""
    checks = "".join(f'<label><input type="checkbox" name="meals" value="{escape(m)}" checked> {escape(m)}</label>' for m in meals)
    body = f"""
<h1>{escape(plan['event'])}</h1>
<p class="subtitle">Check the guest list. Add late guests or placeholders (e.g. “Weldon guest 1”) here, and rename them later from the seating plan.</p>
{alerts(ok, "success")}{alerts(errors, "error")}
<div class="stats-grid">{stats}</div>
<div class="card"><div class="flex-between" style="margin-bottom:1rem"><h2 style="margin:0">Guests</h2>
  <span class="text-muted">{len(plan['people'])} in total</span></div>
  <div style="overflow-x:auto"><table class="attendee-table">
    <thead><tr><th>Name</th><th>Sex</th><th>Group</th><th>Keep apart from</th><th>Meals</th><th></th></tr></thead>
    <tbody>{rows}</tbody></table></div></div>
<div class="card mt2"><h2>Add a guest</h2>
  <form method="post"><input type="hidden" name="action" value="add">
    <div class="form-row">
      <div class="form-group"><label>Name *</label><input type="text" name="name" required maxlength="60"></div>
      <div class="form-group"><label>Sex *</label><select name="sex" required><option value="">Choose…</option><option value="male">Male</option><option value="female">Female</option></select></div>
    </div>
    <div class="form-row">
      <div class="form-group"><label>Group / family</label><input type="text" name="group"></div>
      <div class="form-group"><label>Keep apart from (comma-separated)</label><input type="text" name="relations"></div>
    </div>
    <div class="form-group"><label>Would like to sit next to</label><input type="text" name="preferred"></div>
    <div class="form-group"><label>Meals</label><div class="checkbox-group">{checks}</div></div>
    <button type="submit" class="btn btn-primary">Add guest</button>
  </form></div>
<div class="flex-between mt3"><a href="/" class="btn btn-secondary">← Back</a>
  <a href="{'/results' if plan['seating'] else '/configure_tables'}" class="btn btn-primary">{'Back to seating →' if plan['seating'] else 'Set up tables →'}</a></div>"""
    return page("Guests", body, step=2)


# ── Step 3: tables ────────────────────────────────────────────────────────────
@app.route("/configure_tables", methods=["GET", "POST"])
def configure_tables():
    plan = get_plan()
    if not plan:
        return redirect(url_for("upload_file"))
    meals = plan["meals"]
    counts = {m: len(pl.attendees(plan, m)) for m in meals}
    warnings, chosen = [], {}
    if request.method == "POST":
        for i, m in enumerate(meals):
            sizes = [int(s) for s in request.form.getlist(f"sizes-{i}") if s.strip().isdigit()]
            chosen[m] = sizes
            if counts[m] == 0:
                continue
            if not sizes:
                warnings.append(f"{m}: add at least one table.")
            elif sum(sizes) != counts[m]:
                warnings.append(f"{m}: tables seat {sum(sizes)} but {counts[m]} guests are coming.")
            if any(s < 2 for s in sizes):
                warnings.append(f"{m}: every table needs at least 2 seats.")
        if not warnings:
            plan["table_config"] = {m: chosen[m] for m in meals}
            plan["seating"] = {}
            save_plan(plan)
            return redirect(url_for("results"))
    else:
        auto = request.args.get("auto") == "1"
        for m in meals:
            current = plan["table_config"].get(m)
            chosen[m] = (suggest_table_sizes(counts[m]) if auto or not current else current) if counts[m] else []

    blocks = ""
    for i, m in enumerate(meals):
        inputs = "".join(
            f'<div class="size-input-wrap"><input type="number" name="sizes-{i}" value="{s}" min="2" max="200">'
            f'<button type="button" class="remove-table" aria-label="Remove table">×</button></div>' for s in chosen[m])
        blocks += f"""<div class="card meal-sizes" data-need="{counts[m]}" data-i="{i}">
  <div class="flex-between" style="margin-bottom:1rem"><div><h3 style="margin:0">{escape(m)}</h3>
    <span class="text-muted">{counts[m]} guests</span></div>
    <button type="button" class="btn btn-sm btn-secondary add-table">+ Table</button></div>
  <div class="size-inputs">{inputs}</div>
  <p class="text-muted mt1" style="font-size:.8rem">Seats: <strong class="sum">{sum(chosen[m])}</strong> / {counts[m]}</p></div>"""
    regen_note = ('<div class="alert alert-warning">Saving new table sizes creates a fresh seating plan '
                  'and replaces the current one. Save your plan first if you want to keep it.</div>'
                  if plan["seating"] else "")
    body = f"""
<h1>Tables</h1><p class="subtitle">How many seats at each table, for each meal.</p>
{alerts(warnings, "warning")}{regen_note}
<div class="action-bar"><a href="?auto=1" class="btn btn-secondary">✦ Suggest sizes</a></div>
<form method="post">{blocks}
<div class="flex-between mt3"><a href="/attendees" class="btn btn-secondary">← Back</a>
<button type="submit" class="btn btn-primary">Create seating plan →</button></div></form>
<script>
document.querySelectorAll('.meal-sizes').forEach(card => {{
  const wrap = card.querySelector('.size-inputs'), sum = card.querySelector('.sum'), need = +card.dataset.need;
  const update = () => {{
    let t = 0; wrap.querySelectorAll('input').forEach(i => t += +i.value || 0);
    sum.textContent = t; sum.style.color = t === need ? 'var(--sage)' : 'var(--rust)';
  }};
  card.querySelector('.add-table').addEventListener('click', () => {{
    const d = document.createElement('div'); d.className = 'size-input-wrap';
    d.innerHTML = '<input type="number" min="2" max="200" value="8"><button type="button" class="remove-table" aria-label="Remove table">×</button>';
    d.querySelector('input').name = 'sizes-' + card.dataset.i;
    wrap.appendChild(d); update();
  }});
  wrap.addEventListener('click', e => {{
    if (e.target.classList.contains('remove-table') && wrap.children.length > 1) {{ e.target.parentNode.remove(); update(); }}
  }});
  wrap.addEventListener('input', update); update();
}});
</script>"""
    return page("Tables", body, step=3)


# ── Step 4: seating ───────────────────────────────────────────────────────────
@app.route("/results")
def results():
    plan = get_plan()
    if not plan:
        return redirect(url_for("upload_file"))
    boot = json.dumps({"generate": not plan["seating"]}).replace("</", "<\\/")
    body = """<div id="app"><div class="spinner-wrap"><div class="spinner"></div>
<p class="text-muted" id="loading-msg">Loading…</p></div></div>"""
    scripts = f'<script>window.BOOT = {boot};</script><script src="/static/results.js?v={ASSET_V}"></script>'
    return page("Seating", body, step=4, wide=True, scripts=scripts)


# ── API ───────────────────────────────────────────────────────────────────────
def _with_plan(fn):
    plan = get_plan()
    if not plan:
        return api_error("Your session has expired. Upload your guest list or open a saved plan.", 409)
    try:
        result = fn(plan)
    except pl.PlanError as e:
        return api_error(str(e))
    save_plan(plan)
    payload = state_payload(plan)
    if result:
        payload.update(result)
    return jsonify(payload)


def _body():
    return request.get_json(silent=True) or {}


@app.get("/api/state")
def api_state():
    plan = get_plan()
    if not plan:
        return api_error("No plan loaded.", 409)
    return jsonify(state_payload(plan))


@app.post("/api/regenerate")
def api_regenerate():
    meal = _body().get("meal")

    def run(plan):
        if meal:
            if meal not in plan["meals"]:
                raise pl.PlanError("Unknown meal.")
            pl.regenerate_meal(plan, meal)
        else:
            pl.regenerate_all(plan)
    return _with_plan(run)


@app.post("/api/options")
def api_options():
    b = _body()
    plan = get_plan()
    if not plan:
        return api_error("No plan loaded.", 409)
    try:
        return jsonify({"options": pl.swap_options(plan, b.get("meal"), b.get("name"))})
    except pl.PlanError as e:
        return api_error(str(e))


@app.post("/api/swap")
def api_swap():
    b = _body()
    return _with_plan(lambda plan: pl.swap(plan, b.get("meal"), b.get("a"), b.get("b")))


@app.post("/api/lock")
def api_lock():
    b = _body()
    return _with_plan(lambda plan: pl.set_lock(plan, b.get("meal"), b.get("name"), bool(b.get("locked"))))


@app.post("/api/rename")
def api_rename():
    b = _body()
    return _with_plan(lambda plan: pl.rename(plan, b.get("old"), b.get("new"), b.get("sex")))


@app.post("/api/add_guest")
def api_add_guest():
    b = _body()
    return _with_plan(lambda plan: pl.add_guest(plan, b.get("name"), b.get("sex"), b.get("meals") or []))


@app.post("/api/remove_guest")
def api_remove_guest():
    b = _body()
    return _with_plan(lambda plan: pl.remove_guest(plan, b.get("name"), b.get("meal") or None))


@app.post("/api/keep_apart")
def api_keep_apart():
    b = _body()
    if b.get("remove"):
        return _with_plan(lambda plan: pl.remove_keep_apart(plan, b.get("a"), b.get("b")))
    return _with_plan(lambda plan: pl.add_keep_apart(plan, b.get("a"), b.get("b")))


@app.post("/api/history")
def api_history():
    f = request.files.get("file")
    if not f:
        return api_error("Choose a file.")
    raw = f.read()

    def run(plan):
        return {"added": pl.add_history(plan, pl.history_from_file(raw, f.filename))}
    return _with_plan(run)


@app.post("/api/history_remove")
def api_history_remove():
    return _with_plan(lambda plan: pl.remove_history(plan, _body().get("event")))


@app.post("/api/load_plan")
def api_load_plan():
    try:
        plan = pl.load_plan(_body())
    except pl.PlanError as e:
        return api_error(str(e))
    save_plan(plan)
    return jsonify(state_payload(plan))


# ── Downloads ─────────────────────────────────────────────────────────────────
DOWNLOADS = {
    "diagrams": ("table-diagrams.pdf", "application/pdf"),
    "diagrams4": ("table-diagrams-4-per-page.pdf", "application/pdf"),
    "lists": ("table-lists.pdf", "application/pdf"),
    "who": ("who-sits-where.pdf", "application/pdf"),
    "cards": ("place-cards.pdf", "application/pdf"),
    "csv": ("seating.csv", "text/csv"),
    "plan": ("plan.json", "application/json"),
}


@app.get("/download/<kind>")
def download(kind):
    plan = get_plan()
    if not plan or kind not in DOWNLOADS:
        return redirect(url_for("results"))
    name, mime = DOWNLOADS[kind]
    data = {
        "diagrams": lambda: pdfs.diagrams_pdf(plan, 1),
        "diagrams4": lambda: pdfs.diagrams_pdf(plan, 4),
        "lists": lambda: pdfs.table_lists_pdf(plan),
        "who": lambda: pdfs.who_sits_where_pdf(plan),
        "cards": lambda: pdfs.place_cards_pdf(plan),
        "csv": lambda: pdfs.seating_csv(plan),
        "plan": lambda: json.dumps(pl.export_plan(plan), indent=1).encode("utf-8"),
    }[kind]()
    prefix = secure_filename(plan["event"]) or "table-plan"
    return send_file(io.BytesIO(data), as_attachment=True, download_name=f"{prefix}-{name}", mimetype=mime)


# Old links keep working
@app.get("/download_list_pdf/<int:_v>")
def _old_list(_v):
    return redirect(url_for("download", kind="lists"))


@app.get("/download_diagram_pdf/<int:_v>")
def _old_diagrams(_v):
    return redirect(url_for("download", kind="diagrams"))


@app.get("/download_csv")
def _old_csv():
    return redirect(url_for("download", kind="csv"))


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
            host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
