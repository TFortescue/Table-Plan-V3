# Table Planner

Seating plans for weekends with several meals. It alternates men and women, keeps relations and keep-apart pairs separate, seats preferred neighbours together, and avoids anyone sitting next to the same person twice, both within the weekend and compared with past weekends.

## Using it

1. **Upload** a guest CSV (or open a saved plan file).
2. **Guests**: check the list. Add late guests or placeholders like "Weldon guest 1".
3. **Tables**: set seats per table for each meal ("Suggest sizes" splits evenly).
4. **Seating**: the plan is generated. Then:
   - **Tap a guest** and every other seat at that meal turns **green** (safe swap), **amber** (minor, e.g. two women together) or **red** (would repeat neighbours or break a keep-apart rule, with the reason). Tap a guest to swap, at any table. Every change has **Undo**.
   - **🔒 Lock** guests you're happy with, then **↻ Regenerate** that meal (or everything) to re-seat everyone else around them. Use this for the host at the head of the table too.
   - **✎ Rename** fills in placeholders. **Not at this meal** / **Remove guest** handle drop-outs; **＋ Add guest** handles late additions.
   - **⇆ Keep apart & past events**: pairs who must never sit together, and plans from previous weekends so recent neighbours are kept apart.
   - **💾 Save plan** downloads a file you can reopen later, or add as a past event next time.
   - **🖨 Print**: table diagrams (1 or 4 per page), table lists, an A–Z "who sits where" sheet, fold-over place cards, or a CSV.

Your latest plan is also kept in your browser, so if the server restarts you can pick up where you left off.

## CSV format

```
name,sex,group,relations,preferred people,Friday Dinner,Saturday Lunch
Olivia,female,Smith,Duncan,Tom,Yes,No
Duncan,male,Smith,Olivia,,Yes,Yes
```

- **sex**: male/female (or M/F)
- **group** (optional): family or party. Kept spread out.
- **relations**: people they must *not* sit next to (comma-separated)
- **preferred people**: people they'd like to sit next to
- One column per meal, in the order the meals happen: `Yes` or `No`

Templates: `static/Example_Plan.csv`, `static/Blank_Plan.csv`.

## Run locally

```bash
pip install -r requirements.txt
python app.py        # http://localhost:5000
```

## Hosting (Render)

render.com → **New → Blueprint** → pick this repo. `render.yaml` sets everything up, including `SECRET_KEY`. Every push to `main` redeploys automatically.

On a phone: open the site, then Share → **Add to Home Screen**.

## Code

| File | What it does |
|---|---|
| `app.py` | Web pages, JSON API, downloads |
| `planner.py` | Plan data, clash checks, swap suggestions, edits, save/open |
| `solver.py` | Seating optimiser (simulated annealing across all tables of a meal, with locked seats) |
| `pdfs.py` | Printable outputs |
| `static/results.js` | The interactive seating editor |
| `Table_Plans.py` | CSV reading and validation (also a command-line version) |
