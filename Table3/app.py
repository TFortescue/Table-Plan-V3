import os
import io
import threading
import uuid
from math import sin, cos, pi

from flask import (
    Flask, render_template_string, request, redirect,
    url_for, session, flash, send_file, jsonify
)
from werkzeug.utils import secure_filename

import Table_Plans as tp
from seating_solver import solve_multiple_variants, solve_single_meal

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.lib import colors

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-me-in-production")

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# In-memory job store for async solving
_jobs = {}  # job_id -> {"status": "running"|"done"|"error", "seating": ..., "error": ...}
_jobs_lock = threading.Lock()

# ─────────────────────────────────────────────
# Shared CSS / design system
# ─────────────────────────────────────────────
BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@400;600;700&family=Lato:wght@300;400;700&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --ink:     #1a1410;
  --paper:   #faf8f4;
  --cream:   #f2ede4;
  --gold:    #b8963e;
  --gold-lt: #d4b06a;
  --rust:    #8b3a2f;
  --sage:    #5a6e58;
  --muted:   #7a6f65;
  --border:  #d8d0c4;
  --shadow:  rgba(26,20,16,.12);
  --radius:  4px;
}

html { font-size: 16px; }

body {
  font-family: 'Lato', sans-serif;
  background: var(--paper);
  color: var(--ink);
  min-height: 100vh;
}

/* ── Header ── */
.site-header {
  background: var(--ink);
  padding: 0 2rem;
  display: flex;
  align-items: center;
  gap: 2rem;
  height: 64px;
  border-bottom: 3px solid var(--gold);
}
.site-header .logo {
  font-family: 'Playfair Display', serif;
  font-size: 1.4rem;
  color: var(--gold-lt);
  letter-spacing: .04em;
  text-decoration: none;
  white-space: nowrap;
}
.site-header nav { display: flex; gap: 0; margin-left: auto; }
.site-header nav a {
  color: #c8bfb3;
  text-decoration: none;
  font-size: .82rem;
  letter-spacing: .1em;
  text-transform: uppercase;
  padding: .5rem 1rem;
  transition: color .2s;
}
.site-header nav a:hover { color: var(--gold-lt); }

/* ── Step progress bar ── */
.step-bar {
  background: var(--cream);
  border-bottom: 1px solid var(--border);
  padding: .75rem 2rem;
  display: flex;
  gap: 0;
  align-items: center;
  overflow-x: auto;
}
.step-item {
  display: flex;
  align-items: center;
  gap: .5rem;
  font-size: .78rem;
  letter-spacing: .08em;
  text-transform: uppercase;
  color: var(--muted);
  white-space: nowrap;
}
.step-item.active { color: var(--gold); font-weight: 700; }
.step-item.done { color: var(--sage); }
.step-num {
  width: 22px; height: 22px;
  border-radius: 50%;
  border: 1.5px solid currentColor;
  display: flex; align-items: center; justify-content: center;
  font-size: .7rem; font-weight: 700;
}
.step-item.active .step-num { background: var(--gold); border-color: var(--gold); color: #fff; }
.step-item.done .step-num { background: var(--sage); border-color: var(--sage); color: #fff; }
.step-sep { margin: 0 .75rem; color: var(--border); font-size: .9rem; }

/* ── Layout ── */
.page { max-width: 900px; margin: 0 auto; padding: 2.5rem 1.5rem 4rem; }
.page-wide { max-width: 1200px; margin: 0 auto; padding: 2rem 1.5rem 4rem; }

h1 {
  font-family: 'Playfair Display', serif;
  font-size: 2rem;
  font-weight: 700;
  color: var(--ink);
  line-height: 1.2;
  margin-bottom: .4rem;
}
h2 {
  font-family: 'Playfair Display', serif;
  font-size: 1.4rem;
  font-weight: 600;
  margin-bottom: 1rem;
}
h3 { font-size: 1rem; font-weight: 700; margin-bottom: .5rem; letter-spacing: .04em; }
.subtitle { color: var(--muted); font-size: .95rem; margin-bottom: 2rem; }
.divider { border: none; border-top: 1px solid var(--border); margin: 2rem 0; }

/* ── Cards ── */
.card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1.5rem;
  box-shadow: 0 1px 4px var(--shadow);
}
.card + .card { margin-top: 1.25rem; }

/* ── Buttons ── */
.btn {
  display: inline-flex; align-items: center; gap: .4rem;
  font-family: 'Lato', sans-serif;
  font-size: .82rem;
  font-weight: 700;
  letter-spacing: .1em;
  text-transform: uppercase;
  padding: .6rem 1.4rem;
  border-radius: var(--radius);
  border: none;
  cursor: pointer;
  text-decoration: none;
  transition: all .18s;
  white-space: nowrap;
}
.btn-primary { background: var(--gold); color: #fff; }
.btn-primary:hover { background: var(--gold-lt); }
.btn-secondary { background: transparent; border: 1.5px solid var(--border); color: var(--ink); }
.btn-secondary:hover { border-color: var(--gold); color: var(--gold); }
.btn-danger { background: var(--rust); color: #fff; }
.btn-danger:hover { opacity: .85; }
.btn-sm { font-size: .72rem; padding: .35rem .85rem; }
.btn-ghost { background: transparent; color: var(--muted); border: 1.5px solid var(--border); }
.btn-ghost:hover { color: var(--ink); border-color: var(--ink); }

/* ── Forms ── */
.form-group { margin-bottom: 1.25rem; }
label { display: block; font-size: .8rem; font-weight: 700; letter-spacing: .07em; text-transform: uppercase; color: var(--muted); margin-bottom: .4rem; }
input[type=text], input[type=number], select, textarea {
  width: 100%;
  padding: .55rem .75rem;
  border: 1.5px solid var(--border);
  border-radius: var(--radius);
  font-family: 'Lato', sans-serif;
  font-size: .95rem;
  background: var(--paper);
  color: var(--ink);
  transition: border-color .18s;
}
input:focus, select:focus, textarea:focus {
  outline: none;
  border-color: var(--gold);
}
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.form-row-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1rem; }
@media (max-width: 600px) { .form-row, .form-row-3 { grid-template-columns: 1fr; } }

/* ── Alerts / flash ── */
.alert {
  border-radius: var(--radius);
  padding: .8rem 1rem;
  font-size: .9rem;
  margin-bottom: 1rem;
  border-left: 4px solid;
}
.alert-warning { background: #fdf6ec; border-color: var(--gold); color: #7a5c1e; }
.alert-error   { background: #fdf0ee; border-color: var(--rust); color: var(--rust); }
.alert-success { background: #eef5ee; border-color: var(--sage); color: var(--sage); }
.alert-info    { background: #f0f4ff; border-color: #5a7ab8; color: #2d4a7a; }

/* ── Badge ── */
.badge {
  display: inline-block;
  font-size: .68rem; font-weight: 700;
  letter-spacing: .06em; text-transform: uppercase;
  padding: .15rem .5rem;
  border-radius: 2px;
}
.badge-male   { background: #dde8f5; color: #2d4a7a; }
.badge-female { background: #f5ddeb; color: #7a2d4a; }
.badge-new    { background: #edf5dd; color: #3a5a1e; }

/* ── Table layout ── */
.table-card {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  box-shadow: 0 1px 4px var(--shadow);
}
.table-card-header {
  background: var(--cream);
  border-bottom: 1px solid var(--border);
  padding: .7rem 1rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.table-card-header h3 { margin: 0; font-size: .9rem; }
.seat-list { padding: .5rem 0; }
.seat-row {
  display: flex;
  align-items: center;
  gap: .6rem;
  padding: .35rem 1rem;
  border-bottom: 1px solid #f0ece6;
  font-size: .9rem;
  transition: background .12s;
}
.seat-row:last-child { border-bottom: none; }
.seat-row:hover { background: var(--paper); }
.seat-num {
  width: 24px; height: 24px;
  background: var(--cream);
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: .7rem; font-weight: 700; color: var(--muted);
  flex-shrink: 0;
}
.seat-name { flex: 1; font-weight: 400; }

/* ── Circular diagram SVG ── */
.diagram-wrap { display: flex; justify-content: center; padding: 1rem; }
svg.table-svg { max-width: 300px; width: 100%; }

/* ── Stats grid ── */
.stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: .75rem; margin-bottom: 2rem; }
.stat-box {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 1rem;
  text-align: center;
}
.stat-num { font-family: 'Playfair Display', serif; font-size: 2rem; color: var(--gold); line-height: 1; }
.stat-label { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); margin-top: .25rem; }

/* ── Meal section ── */
.meal-section { margin-bottom: 2.5rem; }
.meal-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 1rem;
  padding-bottom: .5rem;
  border-bottom: 2px solid var(--gold);
}
.meal-header h2 { margin: 0; }
.meal-actions { display: flex; gap: .5rem; align-items: center; }

/* ── Tables grid ── */
.tables-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 1rem; }

/* ── Upload drop zone ── */
.drop-zone {
  border: 2px dashed var(--border);
  border-radius: var(--radius);
  padding: 3rem 2rem;
  text-align: center;
  cursor: pointer;
  transition: all .2s;
  background: var(--cream);
  margin-bottom: 1.5rem;
}
.drop-zone:hover, .drop-zone.drag-over {
  border-color: var(--gold);
  background: #fdf6e8;
}
.drop-zone .icon { font-size: 2.5rem; margin-bottom: .75rem; }
.drop-zone p { color: var(--muted); font-size: .9rem; }
.drop-zone strong { color: var(--gold); }
input[type=file] { display: none; }

/* ── Table size inputs ── */
.size-inputs { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }
.size-input-wrap { position: relative; }
.size-input-wrap input { width: 60px; text-align: center; }
.remove-table { position: absolute; top: -6px; right: -6px; width: 16px; height: 16px; border-radius: 50%; background: var(--rust); color: #fff; border: none; cursor: pointer; font-size: .65rem; line-height: 16px; text-align: center; }

/* ── Attendee table ── */
.attendee-table { width: 100%; border-collapse: collapse; font-size: .88rem; }
.attendee-table th { text-align: left; font-size: .72rem; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); padding: .5rem .75rem; border-bottom: 1px solid var(--border); }
.attendee-table td { padding: .4rem .75rem; border-bottom: 1px solid #f0ece6; }
.attendee-table tr:last-child td { border-bottom: none; }
.attendee-table tr:hover td { background: var(--paper); }

/* ── Spinner ── */
.spinner-wrap { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 300px; gap: 1.5rem; }
.spinner {
  width: 48px; height: 48px;
  border: 4px solid var(--cream);
  border-top-color: var(--gold);
  border-radius: 50%;
  animation: spin .9s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ── Checkbox group ── */
.checkbox-group { display: flex; flex-wrap: wrap; gap: .5rem; }
.checkbox-group label {
  display: flex; align-items: center; gap: .3rem;
  font-size: .82rem; text-transform: none; letter-spacing: 0;
  font-weight: 400; color: var(--ink);
  cursor: pointer;
  background: var(--cream);
  border: 1.5px solid var(--border);
  border-radius: var(--radius);
  padding: .3rem .65rem;
  transition: all .15s;
}
.checkbox-group label:hover { border-color: var(--gold); }
.checkbox-group input[type=checkbox] { accent-color: var(--gold); }
.checkbox-group label:has(input:checked) { border-color: var(--gold); background: #fdf6e8; }

/* ── Person stats table ── */
.person-stats { font-size: .85rem; }
.person-stats td, .person-stats th { padding: .35rem .6rem; }
.repeat-tag { font-size: .75rem; color: var(--rust); }

/* ── Swap modal ── */
.modal-backdrop {
  display: none;
  position: fixed; inset: 0;
  background: rgba(0,0,0,.45);
  z-index: 100;
  align-items: center;
  justify-content: center;
}
.modal-backdrop.open { display: flex; }
.modal {
  background: #fff;
  border-radius: var(--radius);
  padding: 2rem;
  width: min(480px, 95vw);
  box-shadow: 0 8px 32px rgba(0,0,0,.25);
}
.modal h2 { font-size: 1.2rem; margin-bottom: 1rem; }

/* ── Misc ── */
.text-muted { color: var(--muted); font-size: .85rem; }
.mt1 { margin-top: .5rem; }
.mt2 { margin-top: 1rem; }
.mt3 { margin-top: 1.5rem; }
.flex { display: flex; align-items: center; gap: .75rem; }
.flex-between { display: flex; justify-content: space-between; align-items: center; }
.action-bar { display: flex; gap: .75rem; flex-wrap: wrap; margin-bottom: 2rem; }
"""

# ─────────────────────────────────────────────
# Base layout macro
# ─────────────────────────────────────────────
def base_page(title, body, step=None, wide=False):
    steps = [
        (1, "Upload"),
        (2, "Attendees"),
        (3, "Tables"),
        (4, "Results"),
    ]
    step_html = ""
    for i, (n, label) in enumerate(steps):
        cls = "active" if step == n else ("done" if step and step > n else "")
        step_html += f'<span class="step-item {cls}"><span class="step-num">{n}</span>{label}</span>'
        if i < len(steps) - 1:
            step_html += '<span class="step-sep">›</span>'

    container = "page-wide" if wide else "page"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — Table Planner</title>
<style>{BASE_CSS}</style>
</head>
<body>
<header class="site-header">
  <a href="/" class="logo">⬡ Table Planner</a>
  <nav>
    <a href="/">Upload</a>
    <a href="/attendees">Attendees</a>
    <a href="/configure_tables">Tables</a>
    <a href="/results">Results</a>
  </nav>
</header>
{"" if not step else f'<div class="step-bar">{step_html}</div>'}
<div class="{container}">
{body}
</div>
</body>
</html>"""


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def get_all_people():
    csv_path = session.get("csv_path")
    base_people = tp.read_people_from_csv(csv_path) if csv_path else []
    for e in session.get("extra_people", []):
        try:
            base_people.append(tp.Person(
                pid=e.get("id") or e["name"],
                name=e["name"], sex=e["sex"],
                relations=e.get("relations", []),
                preferred=e.get("preferred", []),
                meals=e.get("meals", []),
                group=e.get("group", ""),
            ))
        except Exception:
            continue
    return base_people


def tables_to_serializable(tables):
    return [[{"name": p.name, "sex": p.sex} for p in table] for table in tables]


def build_global_pairs_from_seating(seating, exclude_meal=None):
    pairs = set()
    if not seating:
        return pairs
    for meal_name, tables in seating.items():
        if exclude_meal and meal_name == exclude_meal:
            continue
        for table in tables:
            n = len(table)
            if n < 2:
                continue
            for i in range(n):
                a = table[i].get("name") if isinstance(table[i], dict) else table[i].name
                b = table[(i+1)%n].get("name") if isinstance(table[(i+1)%n], dict) else table[(i+1)%n].name
                if a and b:
                    pairs.add(tuple(sorted((a, b))))
    return pairs


def suggest_table_sizes(n, preferred_sizes=(10, 12, 8)):
    if n <= 0:
        return []
    sizes = []
    remaining = n
    while remaining > 0:
        chosen = next((s for s in preferred_sizes if remaining - s >= 0), None)
        sizes.append(chosen if chosen else remaining)
        if not chosen:
            break
        remaining -= chosen
    return sizes


def build_summary(seating, meals):
    summaries = {}
    for meal in meals:
        tables = seating.get(meal, [])
        same_sex_pairs = 0
        for table in tables:
            n = len(table)
            for i in range(n):
                a = table[i]
                b = table[(i+1)%n]
                if a.get("sex") == b.get("sex"):
                    same_sex_pairs += 1
        summaries[meal] = {"same_sex_pairs": same_sex_pairs}
    return summaries


def build_person_stats(seating):
    stats = {}
    for tables in seating.values():
        for table in tables:
            n = len(table)
            if n < 2:
                continue
            for i in range(n):
                a = table[i]
                b = table[(i+1)%n]
                name_a = a.get("name"); name_b = b.get("name")
                sex_a = (a.get("sex") or "").lower()
                sex_b = (b.get("sex") or "").lower()
                for (main_name, main_sex, other_name, other_sex) in [
                    (name_a, sex_a, name_b, sex_b),
                    (name_b, sex_b, name_a, sex_a),
                ]:
                    if not main_name:
                        continue
                    entry = stats.setdefault(main_name, {
                        "sex": main_sex,
                        "same_sex_neighbours": 0,
                        "total_neighbours": 0,
                        "neighbour_counts": {},
                    })
                    entry["total_neighbours"] += 1
                    entry["neighbour_counts"][other_name] = entry["neighbour_counts"].get(other_name, 0) + 1
                    if main_sex and other_sex and main_sex == other_sex:
                        entry["same_sex_neighbours"] += 1
    for val in stats.values():
        val["repeat_neighbours"] = [
            f"{n} ({c}x)" for n, c in sorted(val["neighbour_counts"].items()) if c > 1
        ]
        del val["neighbour_counts"]
    return dict(sorted(stats.items(), key=lambda kv: kv[0].lower()))


def make_circular_svg(table, size=260):
    """Generate an SVG circular seating diagram for a table."""
    n = len(table)
    if n == 0:
        return "<p class='text-muted'>No seats.</p>"
    cx, cy, r = size/2, size/2, size*0.37
    seat_r = max(10, min(18, 220/n))
    lines = [f'<svg class="table-svg" viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg">']
    # table circle
    lines.append(f'<circle cx="{cx}" cy="{cy}" r="{r*0.55}" fill="#f2ede4" stroke="#d8d0c4" stroke-width="1.5"/>')
    lines.append(f'<text x="{cx}" y="{cy+5}" text-anchor="middle" font-size="11" fill="#7a6f65" font-family="Lato,sans-serif">TABLE</text>')
    for i, person in enumerate(table):
        angle = (2*pi * i / n) - pi/2
        px = cx + r * cos(angle)
        py = cy + r * sin(angle)
        sex = (person.get("sex") or "").lower()
        fill = "#dde8f5" if sex == "male" else "#f5ddeb"
        stroke = "#5a7ab8" if sex == "male" else "#b85a7a"
        lines.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="{seat_r}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        name = (person.get("name") or "")
        display = name[:8] + ("…" if len(name) > 8 else "")
        lines.append(f'<text x="{px:.1f}" y="{py+4:.1f}" text-anchor="middle" font-size="{max(7,seat_r*0.72):.0f}" fill="#1a1410" font-family="Lato,sans-serif" font-weight="700">{display}</text>')
    lines.append("</svg>")
    return "\n".join(lines)


# ─────────────────────────────────────────────
# STEP 1 — Upload
# ─────────────────────────────────────────────
@app.route("/", methods=["GET", "POST"])
def upload_file():
    errors = []
    if request.method == "POST":
        file = request.files.get("csv_file")
        if not file or file.filename == "":
            errors.append("Please select a CSV file.")
        else:
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)
            session["csv_path"] = filepath
            meals = tp.read_meals_from_csv(filepath)
            session["meals"] = meals
            session["extra_people"] = []
            session.pop("seating", None)
            session.pop("table_config", None)
            session.pop("job_id", None)
            people = tp.read_people_from_csv(filepath)
            errs = tp.validate_people(people)
            if errs:
                errors.extend(errs)
            else:
                return redirect(url_for("attendees"))

    body = f"""
<h1>Seating Plan Generator</h1>
<p class="subtitle">Upload a guest CSV to get started. <a href="/static/Example_Plan.csv" style="color:var(--gold)">Download example CSV</a></p>
{"".join(f'<div class="alert alert-error">{e}</div>' for e in errors)}
<div class="card">
  <form method="post" enctype="multipart/form-data" id="upload-form">
    <div class="drop-zone" id="drop-zone" onclick="document.getElementById('csv-input').click()">
      <div class="icon">📋</div>
      <p><strong>Click to choose a file</strong> or drag and drop here</p>
      <p class="mt1" id="file-label">CSV files only</p>
    </div>
    <input type="file" name="csv_file" id="csv-input" accept=".csv" onchange="fileChosen(this)">
    <button type="submit" class="btn btn-primary" style="width:100%">Upload &amp; Continue →</button>
  </form>
</div>
<div class="card mt2">
  <h3>CSV Format</h3>
  <p class="text-muted" style="margin-top:.5rem">Your CSV must have these columns in order:</p>
  <code style="display:block;background:var(--cream);padding:.75rem;border-radius:4px;font-size:.82rem;margin-top:.75rem;overflow-x:auto">name, sex, relations, preferred people, [Meal 1], [Meal 2], ...</code>
  <p class="text-muted mt2">Meal columns contain <strong>Yes</strong> or <strong>No</strong>. Add as many meal columns as you need.</p>
</div>
<script>
const dz = document.getElementById('drop-zone');
dz.addEventListener('dragover', e => {{ e.preventDefault(); dz.classList.add('drag-over'); }});
dz.addEventListener('dragleave', () => dz.classList.remove('drag-over'));
dz.addEventListener('drop', e => {{
  e.preventDefault(); dz.classList.remove('drag-over');
  const file = e.dataTransfer.files[0];
  if (file) {{
    const dt = new DataTransfer(); dt.items.add(file);
    document.getElementById('csv-input').files = dt.files;
    fileChosen({{ files: [file] }});
  }}
}});
function fileChosen(inp) {{
  const f = inp.files ? inp.files[0] : null;
  if (f) document.getElementById('file-label').textContent = '✓ ' + f.name;
}}
</script>
"""
    return base_page("Upload", body, step=1)


# ─────────────────────────────────────────────
# STEP 2 — Attendees
# ─────────────────────────────────────────────
@app.route("/attendees", methods=["GET", "POST"])
def attendees():
    csv_path = session.get("csv_path")
    meals = session.get("meals", [])
    if not csv_path:
        return redirect(url_for("upload_file"))

    flash_msgs = []

    if request.method == "POST":
        action = request.form.get("action", "add")
        if action == "remove":
            name = request.form.get("name", "")
            extra = [p for p in session.get("extra_people", []) if p.get("name") != name]
            session["extra_people"] = extra
            flash_msgs.append(("success", f"Removed {name}."))
        else:
            name = request.form.get("name", "").strip()
            sex = request.form.get("sex", "").strip().lower()
            group = request.form.get("group", "").strip()
            relations = [r.strip() for r in request.form.get("relations","").split(",") if r.strip()]
            preferred = [p.strip() for p in request.form.get("preferred","").split(",") if p.strip()]
            meals_sel = request.form.getlist("meals")
            if not name or sex not in ("male", "female"):
                flash_msgs.append(("error", "Name and sex (male/female) are required."))
            else:
                extra = session.get("extra_people", [])
                extra.append({"id": name, "name": name, "sex": sex, "group": group,
                               "relations": relations, "preferred": preferred, "meals": meals_sel})
                session["extra_people"] = extra
                flash_msgs.append(("success", f"Added {name}."))

    csv_people = tp.read_people_from_csv(csv_path)
    extra_people = session.get("extra_people", [])

    combined = [{"name": p.name, "sex": p.sex, "meals": p.meals,
                 "group": getattr(p,"group",""), "source": "CSV"} for p in csv_people]
    for e in extra_people:
        combined.append({"name": e["name"], "sex": e["sex"], "meals": e.get("meals",[]),
                          "group": e.get("group",""), "source": "Added"})

    meal_counts = {}
    for meal in meals:
        plist = [p for p in combined if meal in p["meals"]]
        males = sum(1 for p in plist if p["sex"].lower()=="male")
        meal_counts[meal] = {"total": len(plist), "males": males, "females": len(plist)-males}

    flash_html = "".join(f'<div class="alert alert-{"success" if t=="success" else "error"}">{m}</div>' for t,m in flash_msgs)

    # Build attendee rows
    rows = ""
    for p in combined:
        meal_badges = " ".join(f'<span class="badge" style="background:var(--cream);color:var(--muted)">{m}</span>' for m in p["meals"])
        src_badge = '<span class="badge badge-new">Added</span>' if p["source"]=="Added" else ""
        sex_badge = f'<span class="badge badge-{p["sex"].lower()}">{p["sex"].title()}</span>'
        remove_btn = ""
        if p["source"] == "Added":
            remove_btn = f'''<form method="post" style="display:inline">
              <input type="hidden" name="action" value="remove">
              <input type="hidden" name="name" value="{p["name"]}">
              <button type="submit" class="btn btn-sm btn-danger">Remove</button>
            </form>'''
        rows += f"""<tr>
          <td><strong>{p["name"]}</strong> {src_badge}</td>
          <td>{sex_badge}</td>
          <td>{p.get("group","") or "—"}</td>
          <td>{meal_badges or "—"}</td>
          <td>{remove_btn}</td>
        </tr>"""

    # Meal summary
    meal_summary = ""
    for meal in meals:
        mc = meal_counts[meal]
        meal_summary += f"""<div class="stat-box">
          <div class="stat-num">{mc["total"]}</div>
          <div class="stat-label">{meal}</div>
          <div class="text-muted" style="font-size:.75rem;margin-top:.25rem">{mc["males"]}M · {mc["females"]}F</div>
        </div>"""

    # Meal checkboxes for add form
    meal_checks = "".join(
        f'<label><input type="checkbox" name="meals" value="{m}"> {m}</label>'
        for m in meals
    )

    body = f"""
<h1>Attendees</h1>
<p class="subtitle">Review your guest list and add anyone who isn't in the CSV.</p>
{flash_html}
<div class="stats-grid">{meal_summary}</div>

<div class="card">
  <div class="flex-between" style="margin-bottom:1rem">
    <h2 style="margin:0">Guest List</h2>
    <span class="text-muted">{len(combined)} guests total</span>
  </div>
  <div style="overflow-x:auto">
    <table class="attendee-table">
      <thead><tr><th>Name</th><th>Sex</th><th>Group</th><th>Meals</th><th></th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>

<div class="card mt2">
  <h2>Add a Guest</h2>
  <form method="post">
    <input type="hidden" name="action" value="add">
    <div class="form-row">
      <div class="form-group">
        <label>Name *</label>
        <input type="text" name="name" placeholder="Full name" required>
      </div>
      <div class="form-group">
        <label>Sex *</label>
        <select name="sex" required>
          <option value="">Choose…</option>
          <option value="male">Male</option>
          <option value="female">Female</option>
        </select>
      </div>
    </div>
    <div class="form-row">
      <div class="form-group">
        <label>Group / Family</label>
        <input type="text" name="group" placeholder="e.g. Smith family">
      </div>
      <div class="form-group">
        <label>Relations (comma-separated)</label>
        <input type="text" name="relations" placeholder="e.g. Jane, Bob">
      </div>
    </div>
    <div class="form-group">
      <label>Preferred Neighbours (comma-separated)</label>
      <input type="text" name="preferred" placeholder="e.g. Alice">
    </div>
    <div class="form-group">
      <label>Attending Meals</label>
      <div class="checkbox-group">{meal_checks}</div>
    </div>
    <button type="submit" class="btn btn-primary">Add Guest</button>
  </form>
</div>

<div class="flex-between mt3">
  <a href="/" class="btn btn-secondary">← Back</a>
  <a href="/configure_tables" class="btn btn-primary">Configure Tables →</a>
</div>
"""
    return base_page("Attendees", body, step=2)


# ─────────────────────────────────────────────
# STEP 3 — Configure Tables
# ─────────────────────────────────────────────
@app.route("/configure_tables", methods=["GET", "POST"])
def configure_tables():
    meals = session.get("meals", [])
    if not meals:
        return redirect(url_for("upload_file"))

    people = get_all_people()
    meal_counts = {meal: sum(meal in p.meals for p in people) for meal in meals}
    warnings = []
    saved = {}

    if request.method == "POST":
        table_config = {}
        for meal in meals:
            sizes_raw = request.form.getlist(f"{meal}_table_size")
            sizes = [int(s) for s in sizes_raw if s.strip().isdigit()]
            saved[meal] = sizes
            table_config[meal] = sizes
            total_seats = sum(sizes)
            expected = meal_counts[meal]
            if total_seats != expected:
                warnings.append(f"<strong>{meal}</strong>: table sizes sum to {total_seats}, but {expected} attendees expected.")
            if not sizes:
                warnings.append(f"<strong>{meal}</strong>: you must add at least one table.")
            for s in sizes:
                if s < 2:
                    warnings.append(f"<strong>{meal}</strong>: table size {s} is too small (min 2).")
        if not warnings:
            session["table_config"] = table_config
            session.pop("seating", None)
            session.pop("job_id", None)
            return redirect(url_for("results"))
    else:
        auto_fill = str(request.args.get("auto","")).lower() in ("1","true","yes")
        for meal in meals:
            count = meal_counts.get(meal, 0)
            saved[meal] = suggest_table_sizes(count) if auto_fill else ([count] if count > 0 else [])

    warn_html = "".join(f'<div class="alert alert-warning">{w}</div>' for w in warnings)

    meal_blocks = ""
    for meal in meals:
        count = meal_counts.get(meal, 0)
        sizes = saved.get(meal, [count] if count else [])
        size_inputs = "".join(
            f'<div class="size-input-wrap"><input type="number" name="{meal}_table_size" value="{s}" min="2" max="200" class="table-size-input"><button type="button" class="remove-table" onclick="removeTable(this)">×</button></div>'
            for s in sizes
        )
        meal_blocks += f"""
<div class="card">
  <div class="flex-between" style="margin-bottom:1rem">
    <div>
      <h3 style="margin:0">{meal}</h3>
      <span class="text-muted">{count} attendees</span>
    </div>
    <button type="button" class="btn btn-sm btn-secondary" onclick="addTable(this, '{meal}')">+ Add Table</button>
  </div>
  <div class="size-inputs" id="sizes-{meal}">
    {size_inputs}
  </div>
  <p class="text-muted mt1" style="font-size:.78rem" id="total-{meal}">
    Total seats: <strong id="sum-{meal}">{sum(sizes)}</strong> / {count} needed
  </p>
</div>"""

    body = f"""
<h1>Configure Tables</h1>
<p class="subtitle">Set the number of seats at each table for each meal.</p>
{warn_html}
<div class="action-bar">
  <a href="?auto=1" class="btn btn-secondary">✦ Auto-fill sizes</a>
</div>
<form method="post" id="tables-form">
{meal_blocks}
<div class="flex-between mt3">
  <a href="/attendees" class="btn btn-secondary">← Back</a>
  <button type="submit" class="btn btn-primary">Generate Seating Plan →</button>
</div>
</form>
<script>
function addTable(btn, meal) {{
  const wrap = document.getElementById('sizes-' + meal);
  const div = document.createElement('div');
  div.className = 'size-input-wrap';
  div.innerHTML = '<input type="number" name="' + meal + '_table_size" value="8" min="2" max="200" class="table-size-input"><button type="button" class="remove-table" onclick="removeTable(this)">×</button>';
  wrap.appendChild(div);
  updateTotal(meal);
}}
function removeTable(btn) {{
  const wrap = btn.closest('.size-inputs');
  const meal = wrap.id.replace('sizes-', '');
  if (wrap.querySelectorAll('input').length > 1) {{
    btn.closest('.size-input-wrap').remove();
    updateTotal(meal);
  }}
}}
function updateTotal(meal) {{
  const inputs = document.querySelectorAll('[name="' + meal + '_table_size"]');
  let sum = 0;
  inputs.forEach(i => sum += parseInt(i.value) || 0);
  document.getElementById('sum-' + meal).textContent = sum;
}}
document.querySelectorAll('.table-size-input').forEach(inp => {{
  inp.addEventListener('input', () => {{
    const meal = inp.name.replace('_table_size','');
    updateTotal(meal);
  }});
}});
</script>
"""
    return base_page("Configure Tables", body, step=3)


# ─────────────────────────────────────────────
# Background solver
# ─────────────────────────────────────────────
def _run_solver(job_id, people, meals, table_config):
    try:
        solver_output = solve_multiple_variants(people, meals, table_config, variants=1)
        seating = {}
        for meal in meals:
            variants = solver_output.get(meal, [])
            seating[meal] = tables_to_serializable(variants[0]) if variants else []
        with _jobs_lock:
            _jobs[job_id] = {"status": "done", "seating": seating}
    except Exception as e:
        with _jobs_lock:
            _jobs[job_id] = {"status": "error", "error": str(e)}


@app.route("/solve_async", methods=["POST"])
def solve_async():
    """Start a background solve and return a job_id."""
    people = get_all_people()
    meals = session.get("meals", [])
    table_config = session.get("table_config", {})
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "running"}
    session["job_id"] = job_id
    t = threading.Thread(target=_run_solver, args=(job_id, people, meals, table_config), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/job_status/<job_id>")
def job_status(job_id):
    with _jobs_lock:
        job = _jobs.get(job_id, {})
    if not job:
        return jsonify({"status": "not_found"})
    if job["status"] == "done":
        # Commit seating to session
        session["seating"] = job["seating"]
        with _jobs_lock:
            _jobs.pop(job_id, None)
        return jsonify({"status": "done"})
    return jsonify({"status": job.get("status", "running"),
                    "error": job.get("error", "")})


# ─────────────────────────────────────────────
# STEP 4 — Results
# ─────────────────────────────────────────────
@app.route("/results", methods=["GET", "POST"])
def results():
    meals = session.get("meals", [])
    table_config = session.get("table_config", {})
    if not meals:
        return redirect(url_for("upload_file"))

    seating = session.get("seating")
    people = get_all_people()

    if request.method == "POST":
        action = request.form.get("action")

        if action == "regen_all":
            session.pop("seating", None)
            return redirect(url_for("results"))

        elif action == "swap":
            meal_to_swap = request.form.get("meal")
            try:
                table_idx = int(request.form.get("table_index", "0")) - 1
            except ValueError:
                table_idx = -1
            name_a = request.form.get("name_a", "")
            name_b = request.form.get("name_b", "")
            if seating and meal_to_swap in seating and 0 <= table_idx < len(seating.get(meal_to_swap, [])) and name_a and name_b and name_a != name_b:
                table = seating[meal_to_swap][table_idx]
                idx_a = next((i for i, p in enumerate(table) if p.get("name") == name_a), None)
                idx_b = next((i for i, p in enumerate(table) if p.get("name") == name_b), None)
                if idx_a is not None and idx_b is not None:
                    table[idx_a], table[idx_b] = table[idx_b], table[idx_a]
                    seating[meal_to_swap][table_idx] = table
                    session["seating"] = seating
            return redirect(url_for("results"))

        else:
            # Regen single meal
            meal_to_regen = request.form.get("meal")
            if meal_to_regen and meal_to_regen in meals:
                attendees = [p for p in people if meal_to_regen in p.meals]
                sizes = table_config.get(meal_to_regen, [])
                if not attendees:
                    if seating:
                        seating[meal_to_regen] = []
                        session["seating"] = seating
                else:
                    if not sizes:
                        sizes = [len(attendees)]
                    global_pairs = build_global_pairs_from_seating(seating, exclude_meal=meal_to_regen)
                    new_tables = solve_single_meal(attendees, sizes, global_pairs=global_pairs)
                    if seating is None:
                        seating = {}
                    seating[meal_to_regen] = tables_to_serializable(new_tables)
                    session["seating"] = seating
            return redirect(url_for("results"))

    # ── GET ──
    # If no seating yet, show loading page and kick off async solve
    if not seating:
        body = f"""
<h1>Generating Seating Plans</h1>
<div class="spinner-wrap">
  <div class="spinner"></div>
  <p class="text-muted">Optimising arrangements for {len(people)} guests across {len(meals)} meals…</p>
</div>
<script>
(async function() {{
  const resp = await fetch('/solve_async', {{method:'POST'}});
  const {{job_id}} = await resp.json();
  async function poll() {{
    const r = await fetch('/job_status/' + job_id);
    const data = await r.json();
    if (data.status === 'done') {{
      window.location.href = '/results';
    }} else if (data.status === 'error') {{
      document.querySelector('.spinner-wrap').innerHTML =
        '<div class="alert alert-error">Solver error: ' + data.error + '</div>';
    }} else {{
      setTimeout(poll, 800);
    }}
  }}
  poll();
}})();
</script>
"""
        return base_page("Generating…", body, step=4)

    # ── Render results ──
    summaries = build_summary(seating, meals)
    person_stats = build_person_stats(seating)

    # Global stats
    total_guests = len(person_stats)
    total_same_sex = sum(s["same_sex_pairs"] for s in summaries.values())

    # Meals HTML
    all_names_per_meal = {}
    for meal in meals:
        names = set()
        for table in seating.get(meal, []):
            for p in table:
                names.add(p.get("name",""))
        all_names_per_meal[meal] = sorted(names)

    meal_sections = ""
    for meal in meals:
        tables = seating.get(meal, [])
        total_att = sum(len(t) for t in tables)
        same_sex = summaries[meal]["same_sex_pairs"]
        quality_color = "var(--sage)" if same_sex == 0 else ("var(--gold)" if same_sex <= 2 else "var(--rust)")

        # Table cards
        table_cards = ""
        for ti, table in enumerate(tables, 1):
            seat_rows = ""
            for si, person in enumerate(table, 1):
                sex = (person.get("sex") or "").lower()
                badge = f'<span class="badge badge-{sex}">{sex[0].upper() if sex else "?"}</span>'
                seat_rows += f'<div class="seat-row"><span class="seat-num">{si}</span><span class="seat-name">{person.get("name","")}</span>{badge}</div>'

            # Name options for swap select
            name_options = "".join(f'<option value="{p.get("name","")}">{p.get("name","")}</option>' for p in table)

            svg = make_circular_svg(table)
            table_cards += f"""
<div class="table-card">
  <div class="table-card-header">
    <h3>Table {ti} &mdash; {len(table)} guests</h3>
    <button class="btn btn-sm btn-ghost" onclick="openSwap('{meal}', {ti}, [{','.join('"'+p.get('name','')+'"' for p in table)}])">⇄ Swap</button>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr">
    <div class="seat-list">{seat_rows}</div>
    <div class="diagram-wrap">{svg}</div>
  </div>
</div>"""

        meal_sections += f"""
<div class="meal-section">
  <div class="meal-header">
    <div>
      <h2>{meal}</h2>
      <span class="text-muted">{total_att} guests · {len(tables)} table{"s" if len(tables)!=1 else ""} · <span style="color:{quality_color}">{same_sex} same-sex adjacent pairs</span></span>
    </div>
    <div class="meal-actions">
      <form method="post" style="display:inline">
        <input type="hidden" name="meal" value="{meal}">
        <button type="submit" class="btn btn-sm btn-secondary">↻ Regenerate</button>
      </form>
    </div>
  </div>
  <div class="tables-grid">{table_cards}</div>
</div>"""

    # Person stats table
    stat_rows = ""
    for name, st in person_stats.items():
        repeats = ", ".join(st.get("repeat_neighbours",[]))
        same_n = st.get("same_sex_neighbours", 0)
        color = "color:var(--rust)" if same_n >= 3 else ("color:var(--gold)" if same_n >= 2 else "")
        stat_rows += f"""<tr>
          <td><strong>{name}</strong></td>
          <td><span class="badge badge-{st.get('sex','')}">{st.get('sex','').title()}</span></td>
          <td style="{color}">{same_n}</td>
          <td class="repeat-tag">{repeats or "—"}</td>
        </tr>"""

    # Swap modal
    swap_modal = """
<div class="modal-backdrop" id="swap-modal">
  <div class="modal">
    <h2>Swap Two Guests</h2>
    <form method="post" id="swap-form">
      <input type="hidden" name="action" value="swap">
      <input type="hidden" name="meal" id="swap-meal">
      <input type="hidden" name="table_index" id="swap-table-idx">
      <div class="form-group">
        <label>Guest A</label>
        <select name="name_a" id="swap-a"></select>
      </div>
      <div class="form-group">
        <label>Guest B</label>
        <select name="name_b" id="swap-b"></select>
      </div>
      <div class="flex mt2">
        <button type="submit" class="btn btn-primary">Swap Seats</button>
        <button type="button" class="btn btn-secondary" onclick="closeSwap()">Cancel</button>
      </div>
    </form>
  </div>
</div>
<script>
function openSwap(meal, tableIdx, names) {
  document.getElementById('swap-meal').value = meal;
  document.getElementById('swap-table-idx').value = tableIdx;
  const opts = names.map(n => '<option value="'+n+'">'+n+'</option>').join('');
  document.getElementById('swap-a').innerHTML = opts;
  document.getElementById('swap-b').innerHTML = opts;
  if (names.length > 1) document.getElementById('swap-b').selectedIndex = 1;
  document.getElementById('swap-modal').classList.add('open');
}
function closeSwap() {
  document.getElementById('swap-modal').classList.remove('open');
}
document.getElementById('swap-modal').addEventListener('click', e => {
  if (e.target === e.currentTarget) closeSwap();
});
</script>"""

    body = f"""
<div class="flex-between" style="margin-bottom:1.5rem">
  <div>
    <h1>Seating Plans</h1>
    <p class="subtitle">Drag tables to rearrange. Swap individuals or regenerate any meal.</p>
  </div>
</div>

<div class="stats-grid">
  <div class="stat-box"><div class="stat-num">{total_guests}</div><div class="stat-label">Guests</div></div>
  <div class="stat-box"><div class="stat-num">{len(meals)}</div><div class="stat-label">Meals</div></div>
  <div class="stat-box"><div class="stat-num">{sum(len(seating.get(m,[])) for m in meals)}</div><div class="stat-label">Tables</div></div>
  <div class="stat-box"><div class="stat-num" style="color:{"var(--sage)" if total_same_sex==0 else "var(--gold)"}">{total_same_sex}</div><div class="stat-label">Same-sex pairs</div></div>
</div>

<div class="action-bar">
  <form method="post" style="display:inline">
    <input type="hidden" name="action" value="regen_all">
    <button type="submit" class="btn btn-secondary">↻ Regenerate All</button>
  </form>
  <a href="/download_list_pdf/0" class="btn btn-secondary">⬇ List PDF</a>
  <a href="/download_diagram_pdf/0" class="btn btn-secondary">⬇ Diagram PDF</a>
  <a href="/download_csv" class="btn btn-secondary">⬇ CSV Export</a>
  <a href="/configure_tables" class="btn btn-ghost">← Change Tables</a>
</div>

{meal_sections}

<hr class="divider">
<h2>Guest Statistics</h2>
<p class="text-muted" style="margin-bottom:1rem">Same-sex neighbours across all meals.</p>
<div class="card">
  <div style="overflow-x:auto">
    <table class="attendee-table person-stats">
      <thead><tr><th>Guest</th><th>Sex</th><th>Same-sex neighbours</th><th>Repeat neighbours</th></tr></thead>
      <tbody>{stat_rows}</tbody>
    </table>
  </div>
</div>
{swap_modal}
"""
    return base_page("Results", body, step=4, wide=True)


# ─────────────────────────────────────────────
# PDF: List
# ─────────────────────────────────────────────
@app.route("/download_list_pdf/<int:variant>")
def download_list_pdf(variant):
    meals = session.get("meals", [])
    seating = session.get("seating")
    if not meals or seating is None:
        return redirect(url_for("results"))

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 2 * cm

    def new_page_check(y, needed=0.8*cm):
        if y < margin + needed:
            c.showPage()
            return height - margin
        return y

    y = height - margin
    c.setFont("Helvetica-Bold", 20)
    c.setFillColor(colors.HexColor("#1a1410"))
    c.drawString(margin, y, "Seating Plans")
    y -= 0.5 * cm
    c.setStrokeColor(colors.HexColor("#b8963e"))
    c.setLineWidth(2)
    c.line(margin, y, width - margin, y)
    y -= 0.8 * cm

    for meal in meals:
        y = new_page_check(y, 2 * cm)
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(colors.HexColor("#b8963e"))
        c.drawString(margin, y, meal)
        y -= 0.6 * cm

        tables = seating.get(meal, [])
        for tindex, table in enumerate(tables, 1):
            y = new_page_check(y, 1.2 * cm)
            c.setFont("Helvetica-Bold", 11)
            c.setFillColor(colors.HexColor("#1a1410"))
            c.drawString(margin, y, f"  Table {tindex}  ({len(table)} guests)")
            y -= 0.5 * cm

            for seat, person in enumerate(table, 1):
                y = new_page_check(y)
                name = person.get("name", "Unknown")
                sex = person.get("sex", "?")
                c.setFont("Helvetica", 10)
                c.setFillColor(colors.HexColor("#5a7ab8") if sex == "male" else colors.HexColor("#b85a7a"))
                c.drawString(margin + 0.4*cm, y, f"{seat}.")
                c.setFillColor(colors.HexColor("#1a1410"))
                c.drawString(margin + 0.9*cm, y, f"{name}  ({sex})")
                y -= 0.5 * cm

            y -= 0.3 * cm
        y -= 0.5 * cm

    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="seating_list.pdf", mimetype="application/pdf")


# ─────────────────────────────────────────────
# PDF: Diagrams (fixed: each table on own page)
# ─────────────────────────────────────────────
@app.route("/download_diagram_pdf/<int:variant>")
def download_diagram_pdf(variant):
    meals = session.get("meals", [])
    seating = session.get("seating")
    if not meals or seating is None:
        return redirect(url_for("results"))

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    for meal in meals:
        tables = seating.get(meal, [])
        for tindex, table in enumerate(tables, 1):
            # Each table gets its own page
            c.setFont("Helvetica-Bold", 18)
            c.setFillColor(colors.HexColor("#1a1410"))
            c.drawCentredString(width / 2, height - 1.8*cm, meal)

            c.setFont("Helvetica", 13)
            c.setFillColor(colors.HexColor("#b8963e"))
            c.drawCentredString(width / 2, height - 2.8*cm, f"Table {tindex}  ·  {len(table)} guests")

            # Gold rule
            c.setStrokeColor(colors.HexColor("#b8963e"))
            c.setLineWidth(1.5)
            c.line(2*cm, height - 3.2*cm, width - 2*cm, height - 3.2*cm)

            cx = width / 2
            cy = height / 2 - 0.5*cm
            radius = min(width, height) * 0.30

            # Table circle
            c.setFillColor(colors.HexColor("#f2ede4"))
            c.setStrokeColor(colors.HexColor("#d8d0c4"))
            c.setLineWidth(1.5)
            c.circle(cx, cy, radius * 0.45, fill=1)

            c.setFont("Helvetica", 9)
            c.setFillColor(colors.HexColor("#7a6f65"))
            c.drawCentredString(cx, cy - 3, "TABLE")

            N = len(table)
            if N == 0:
                c.showPage()
                continue

            seat_r = max(14, min(26, radius * 0.22))
            for i, person in enumerate(table):
                angle = (2 * pi * i / N) - pi / 2
                px = cx + radius * cos(angle)
                py = cy + radius * sin(angle)

                sex = (person.get("sex") or "").lower()
                if sex == "male":
                    fill_c = colors.HexColor("#dde8f5")
                    stroke_c = colors.HexColor("#5a7ab8")
                else:
                    fill_c = colors.HexColor("#f5ddeb")
                    stroke_c = colors.HexColor("#b85a7a")

                c.setFillColor(fill_c)
                c.setStrokeColor(stroke_c)
                c.setLineWidth(1.5)
                c.circle(px, py, seat_r, fill=1)

                name = person.get("name", "")
                display = name[:10] + ("…" if len(name) > 10 else "")
                c.setFillColor(colors.HexColor("#1a1410"))
                c.setFont("Helvetica-Bold", max(6, int(seat_r * 0.55)))
                c.drawCentredString(px, py - 2, display)

                # Seat number
                c.setFont("Helvetica", 7)
                c.setFillColor(colors.HexColor("#7a6f65"))
                label_r = radius * 0.62
                lx = cx + label_r * cos(angle)
                ly = cy + label_r * sin(angle)
                c.drawCentredString(lx, ly - 2, str(i + 1))

            # Legend
            c.setFont("Helvetica", 8)
            c.setFillColor(colors.HexColor("#dde8f5"))
            c.setStrokeColor(colors.HexColor("#5a7ab8"))
            c.circle(2.2*cm, 1.5*cm, 5, fill=1)
            c.setFillColor(colors.HexColor("#1a1410"))
            c.drawString(2.6*cm, 1.47*cm, "Male")
            c.setFillColor(colors.HexColor("#f5ddeb"))
            c.setStrokeColor(colors.HexColor("#b85a7a"))
            c.circle(4.5*cm, 1.5*cm, 5, fill=1)
            c.setFillColor(colors.HexColor("#1a1410"))
            c.drawString(4.9*cm, 1.47*cm, "Female")

            c.showPage()

    c.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="seating_diagrams.pdf", mimetype="application/pdf")


# ─────────────────────────────────────────────
# CSV Export
# ─────────────────────────────────────────────
@app.route("/download_csv")
def download_csv():
    meals = session.get("meals", [])
    seating = session.get("seating")
    if not meals or seating is None:
        return redirect(url_for("results"))

    import csv as csv_mod
    buffer = io.StringIO()
    writer = csv_mod.writer(buffer)
    writer.writerow(["Meal", "Table", "Seat", "Name", "Sex"])
    for meal in meals:
        for ti, table in enumerate(seating.get(meal, []), 1):
            for si, person in enumerate(table, 1):
                writer.writerow([meal, ti, si, person.get("name",""), person.get("sex","")])

    out = io.BytesIO(buffer.getvalue().encode("utf-8"))
    return send_file(out, as_attachment=True, download_name="seating_plan.csv", mimetype="text/csv")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    app.run(debug=debug, port=5000)
