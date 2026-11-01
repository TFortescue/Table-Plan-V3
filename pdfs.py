"""Printable outputs. Every function takes a plan dict and returns PDF/CSV bytes.

Seat 1 is drawn at the top of each table and numbers run clockwise, matching
the screen.
"""

import csv
import io
from math import cos, sin, pi

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm, mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

import planner as pl

INK = colors.HexColor("#1a1410")
GOLD = colors.HexColor("#b8963e")
MUTED = colors.HexColor("#7a6f65")
CREAM = colors.HexColor("#f2ede4")
LINE = colors.HexColor("#d8d0c4")
M_FILL, M_LINE = colors.HexColor("#dde8f5"), colors.HexColor("#5a7ab8")
F_FILL, F_LINE = colors.HexColor("#f5ddeb"), colors.HexColor("#b85a7a")


def _new_canvas(title, size=A4):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=size)
    c.setTitle(title)
    return buf, c


def _fit(text, font, max_w, start, smallest=5.5):
    """Largest font size (<= start) at which text fits max_w; truncates if needed."""
    size = start
    while size > smallest and stringWidth(text, font, size) > max_w:
        size -= 0.5
    while stringWidth(text, font, size) > max_w and len(text) > 2:
        text = text[:-2] + "…"
    return text, size


def _all_tables(plan):
    for meal in plan["meals"]:
        for t, table in enumerate(plan["seating"].get(meal, [])):
            yield meal, t, table


# ── Table diagrams ───────────────────────────────────────────────────────────
def _draw_table(c, plan, meal, t, table, x0, y0, w, h, scale):
    """Draw one table diagram inside the box (x0, y0, w, h)."""
    sex = {p["name"]: p["sex"] for p in plan["people"]}
    top = y0 + h
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 18 * scale)
    c.drawCentredString(x0 + w / 2, top - 1.1 * cm * scale, meal)
    c.setFont("Helvetica", 12 * scale)
    c.setFillColor(GOLD)
    c.drawCentredString(x0 + w / 2, top - 1.9 * cm * scale, f"Table {t + 1}  ·  {len(table)} guests")
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.2 * scale)
    c.line(x0 + 1 * cm * scale, top - 2.25 * cm * scale, x0 + w - 1 * cm * scale, top - 2.25 * cm * scale)

    area_top = top - 2.5 * cm * scale
    cx = x0 + w / 2
    cy = y0 + (area_top - y0) / 2
    n = max(len(table), 1)
    seat_r = min(26 * scale, max(13 * scale, 2 * pi * min(w, area_top - y0) * 0.33 / n / 2.3))
    r = min(w, area_top - y0) / 2 - seat_r - 4 * scale

    c.setFillColor(CREAM)
    c.setStrokeColor(LINE)
    c.setLineWidth(1.2 * scale)
    c.circle(cx, cy, r * 0.5, fill=1)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 9 * scale)
    c.drawCentredString(cx, cy - 3 * scale, f"TABLE {t + 1}")

    for i, name in enumerate(table):
        a = pi / 2 - 2 * pi * i / n
        px, py = cx + r * cos(a), cy + r * sin(a)
        male = sex.get(name) == "male"
        c.setFillColor(M_FILL if male else F_FILL)
        c.setStrokeColor(M_LINE if male else F_LINE)
        c.setLineWidth(1.4 * scale)
        c.circle(px, py, seat_r, fill=1)
        label, size = _fit(name, "Helvetica-Bold", seat_r * 1.85, seat_r * 0.6)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", size)
        c.drawCentredString(px, py - size * 0.35, label)
        lr = r - seat_r - 7 * scale
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7 * scale)
        c.drawCentredString(cx + lr * cos(a), cy + lr * sin(a) - 2.5 * scale, str(i + 1))


def _legend(c, x, y):
    for dx, label, fill, line in [(0, "Male", M_FILL, M_LINE), (2.2 * cm, "Female", F_FILL, F_LINE)]:
        c.setFillColor(fill)
        c.setStrokeColor(line)
        c.circle(x + dx, y, 4, fill=1)
        c.setFillColor(INK)
        c.setFont("Helvetica", 8)
        c.drawString(x + dx + 8, y - 3, label)


def diagrams_pdf(plan, per_page=1):
    buf, c = _new_canvas(f"{plan['event']} — table diagrams")
    W, H = A4
    tables = list(_all_tables(plan))
    if per_page == 4:
        boxes = [(0, H / 2), (W / 2, H / 2), (0, 0), (W / 2, 0)]
        for k in range(0, len(tables), 4):
            for (bx, by), (meal, t, table) in zip(boxes, tables[k:k + 4]):
                _draw_table(c, plan, meal, t, table, bx + 0.4 * cm, by + 0.9 * cm,
                            W / 2 - 0.8 * cm, H / 2 - 1.2 * cm, 0.62)
            c.setStrokeColor(LINE)
            c.setDash(2, 3)
            c.line(W / 2, 1 * cm, W / 2, H - 1 * cm)
            c.line(1 * cm, H / 2, W - 1 * cm, H / 2)
            c.setDash()
            _legend(c, 1.5 * cm, 0.6 * cm)
            c.showPage()
    else:
        for meal, t, table in tables:
            _draw_table(c, plan, meal, t, table, 1.5 * cm, 2.5 * cm, W - 3 * cm, H - 3.5 * cm, 1.0)
            _legend(c, 2 * cm, 1.5 * cm)
            c.showPage()
    if not tables:
        c.drawString(2 * cm, H - 2 * cm, "No seating generated yet.")
        c.showPage()
    c.save()
    return buf.getvalue()


# ── Lists ────────────────────────────────────────────────────────────────────
def _header(c, title, subtitle, W, H):
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(2 * cm, H - 2 * cm, title)
    c.setFont("Helvetica", 10)
    c.setFillColor(MUTED)
    c.drawString(2 * cm, H - 2.6 * cm, subtitle)
    c.setStrokeColor(GOLD)
    c.setLineWidth(1.5)
    c.line(2 * cm, H - 2.9 * cm, W - 2 * cm, H - 2.9 * cm)
    return H - 3.7 * cm


def table_lists_pdf(plan):
    """Every meal, table by table, in seat order (two columns per page)."""
    buf, c = _new_canvas(f"{plan['event']} — table lists")
    W, H = A4
    sex = {p["name"]: p["sex"] for p in plan["people"]}
    col_w = (W - 4 * cm) / 2
    for meal in plan["meals"]:
        y = _header(c, meal, plan["event"], W, H)
        col, ytop = 0, y
        for t, table in enumerate(plan["seating"].get(meal, [])):
            needed = 0.7 * cm + len(table) * 0.5 * cm + 0.5 * cm
            if y - needed < 1.5 * cm:
                if col == 0:
                    col, y = 1, ytop
                else:
                    c.showPage()
                    y = _header(c, f"{meal} (continued)", plan["event"], W, H)
                    col, ytop = 0, y
            x = 2 * cm + col * col_w
            c.setFont("Helvetica-Bold", 12)
            c.setFillColor(GOLD)
            c.drawString(x, y, f"Table {t + 1}  ({len(table)})")
            y -= 0.6 * cm
            for s, name in enumerate(table, 1):
                c.setFillColor(M_LINE if sex.get(name) == "male" else F_LINE)
                c.circle(x + 0.15 * cm, y + 3, 2.6, fill=1, stroke=0)
                c.setFillColor(MUTED)
                c.setFont("Helvetica", 9)
                c.drawRightString(x + 0.9 * cm, y, f"{s}.")
                c.setFillColor(INK)
                c.setFont("Helvetica", 11)
                c.drawString(x + 1.1 * cm, y, name)
                y -= 0.5 * cm
            y -= 0.5 * cm
        c.showPage()
    c.save()
    return buf.getvalue()


def who_sits_where_pdf(plan):
    """A–Z guest list with table and seat for every meal: one sheet for the door."""
    meals = plan["meals"]
    size = landscape(A4) if len(meals) > 3 else A4
    W, H = size
    buf, c = _new_canvas(f"{plan['event']} — who sits where", size)
    rows = pl.who_sits_where(plan)
    name_w = 5.5 * cm
    col_w = (W - 4 * cm - name_w) / max(len(meals), 1)
    row_h = 0.62 * cm

    def head():
        y = _header(c, "Who sits where", f"{plan['event']}  ·  table · seat", W, H)
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(MUTED)
        c.drawString(2 * cm + 0.2 * cm, y, "GUEST")
        for k, m in enumerate(meals):
            label, sz = _fit(m.upper(), "Helvetica-Bold", col_w - 0.3 * cm, 9)
            c.setFont("Helvetica-Bold", sz)
            c.drawCentredString(2 * cm + name_w + col_w * (k + 0.5), y, label)
        return y - 0.55 * cm

    y = head()
    for i, (name, where) in enumerate(rows):
        if y < 1.5 * cm:
            c.showPage()
            y = head()
        if i % 2 == 0:
            c.setFillColor(colors.HexColor("#faf8f4"))
            c.rect(2 * cm, y - 0.18 * cm, W - 4 * cm, row_h, fill=1, stroke=0)
        c.setFillColor(INK)
        label, sz = _fit(name, "Helvetica-Bold", name_w - 0.4 * cm, 11)
        c.setFont("Helvetica-Bold", sz)
        c.drawString(2 * cm + 0.2 * cm, y, label)
        c.setFont("Helvetica", 11)
        for k, m in enumerate(meals):
            x = 2 * cm + name_w + col_w * (k + 0.5)
            if m in where:
                tno, sno = where[m]
                c.setFillColor(INK)
                c.drawCentredString(x, y, f"T{tno} · {sno}")
            else:
                c.setFillColor(LINE)
                c.drawCentredString(x, y, "—")
        y -= row_h
    c.save()
    return buf.getvalue()


# ── Place cards ──────────────────────────────────────────────────────────────
def place_cards_pdf(plan):
    """Folding tent cards, four per A4 sheet: cut on the dashed lines, fold on
    the dotted line. The name reads the right way up from both sides."""
    W, H = A4
    buf, c = _new_canvas(f"{plan['event']} — place cards")
    names = sorted((p["name"] for p in plan["people"]), key=str.lower)
    cw, ch = W / 2, H / 2  # each card: 105 × 148.5 mm, folded to 105 × 74
    for k in range(0, len(names), 4):
        for j, name in enumerate(names[k:k + 4]):
            x0 = (j % 2) * cw
            y0 = H / 2 - (j // 2) * ch
            fold = y0 + ch / 2
            for upside_down in (False, True):
                c.saveState()
                if upside_down:
                    c.translate(x0 + cw / 2, fold + ch / 4)
                    c.rotate(180)
                else:
                    c.translate(x0 + cw / 2, fold - ch / 4)
                label, sz = _fit(name, "Times-Bold", cw - 18 * mm, 34)
                c.setFillColor(INK)
                c.setFont("Times-Bold", sz)
                c.drawCentredString(0, -sz * 0.3, label)
                c.setStrokeColor(GOLD)
                c.setLineWidth(0.8)
                c.line(-12 * mm, -sz * 0.3 - 9, 12 * mm, -sz * 0.3 - 9)
                c.restoreState()
            c.setStrokeColor(LINE)
            c.setLineWidth(0.5)
            c.setDash(1, 2)
            c.line(x0 + 4 * mm, fold, x0 + cw - 4 * mm, fold)
            c.setDash()
        c.setStrokeColor(colors.HexColor("#bbbbbb"))
        c.setDash(4, 3)
        c.line(W / 2, 0, W / 2, H)
        c.line(0, H / 2, W, H / 2)
        c.setDash()
        c.showPage()
    if not names:
        c.showPage()
    c.save()
    return buf.getvalue()


# ── CSV ──────────────────────────────────────────────────────────────────────
def seating_csv(plan):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Meal", "Table", "Seat", "Name", "Sex"])
    sex = {p["name"]: p["sex"] for p in plan["people"]}
    for meal, t, table in _all_tables(plan):
        for s, name in enumerate(table, 1):
            w.writerow([meal, t + 1, s, name, sex.get(name, "")])
    return out.getvalue().encode("utf-8")
