"""Plan state and operations, independent of Flask.

A plan is a plain dict (JSON-serialisable) so it can live in the session, be
downloaded as a file and reopened later:

    {
      "event": "Shoot Weekend 29th",
      "meals": ["Friday Dinner", ...],                 # in the order they happen
      "people": [{"name", "sex", "group", "relations", "preferred", "meals"}],
      "table_config": {meal: [10, 9]},                 # seats per table
      "seating": {meal: [["Ann", "Bob", ...], ...]},   # seat 1 first, clockwise
      "locks": {meal: ["Ann"]},                        # guests pinned to their seat
      "keep_apart": [["John", "Susie C"]],
      "history": [{"event": "Shoot Weekend 13th", "pairs": [["A", "B"], ...]}],
    }
"""

import csv
import io
import json
import time

import Table_Plans as tp
from solver import (
    Context, fit_sizes, pair, solve_meal,
    W_KEEP_APART, W_RELATION, W_REPEAT, W_PAST_EVENT, W_PREFERRED,
)

PLAN_FORMAT = "table-planner-plan"
PLAN_VERSION = 1


class PlanError(ValueError):
    """A user-facing problem with a request (shown as a message)."""


# ── Creating a plan ──────────────────────────────────────────────────────────
def new_plan(event, meals, people):
    return {
        "event": event or "My event",
        "meals": list(meals),
        "people": people,
        "table_config": {},
        "seating": {},
        "locks": {},
        "keep_apart": [],
        "history": [],
    }


def person_dict(p):
    return {
        "name": p.name, "sex": p.sex, "group": p.group or "",
        "relations": list(p.relations), "preferred": list(p.preferred),
        "meals": list(p.meals),
    }


def plan_from_csv(path, event):
    """Read a guest CSV. Returns (plan, errors)."""
    meals = tp.read_meals_from_csv(path)
    people = tp.read_people_from_csv(path)
    if not people:
        return None, [
            "No guests could be read from that file. Check it has the columns "
            "name, sex, relations, preferred people, then one column per meal, "
            "and that sex is male/female (or M/F)."
        ]
    if not meals:
        return None, ["No meal columns found after the 'preferred people' column."]
    errors = tp.validate_people(people)
    if errors:
        return None, errors
    return new_plan(event, meals, [person_dict(p) for p in people]), []


def plan_from_builder(data):
    """Build a plan from the no-CSV builder:
    {"event", "meals": [...], "guests": [{"name", "sex", "meals": [...], "partner"?}]}
    Partners are kept apart (added to each other's relations)."""
    if not isinstance(data, dict):
        raise PlanError("Nothing to create.")
    meals = []
    for m in data.get("meals") or []:
        m = " ".join(str(m).split())[:40]
        if m and m not in meals:
            meals.append(m)
    if not meals:
        raise PlanError("Add at least one meal.")
    guests = data.get("guests") or []
    if len(guests) < 2:
        raise PlanError("Add at least two guests.")
    people, seen = [], {}
    for g in guests:
        name = _clean_name(g.get("name"))
        key = name.lower()
        if key in seen:
            raise PlanError(f"{name} is listed twice. Add an initial to tell them apart (e.g. “Tom W”).")
        seen[key] = name
        gm = [m for m in (g.get("meals") or []) if m in meals]
        people.append({"name": name, "sex": _clean_sex(g.get("sex")), "group": "",
                       "relations": [], "preferred": [], "meals": gm})
    by_name = {p["name"]: p for p in people}
    for g in guests:
        a, b = _clean_name(g.get("name")), (g.get("partner") or "").strip()
        if b and b in by_name and b != a:
            for x, y in ((a, b), (b, a)):
                if y not in by_name[x]["relations"]:
                    by_name[x]["relations"].append(y)
    nobody = [p["name"] for p in people if not p["meals"]]
    if len(nobody) == len(people):
        raise PlanError("Tick at least one meal for your guests.")
    people = [p for p in people if p["meals"]]  # guests ticked for no meals aren't coming
    event = " ".join(str(data.get("event") or "").split())[:80] or "My event"
    return new_plan(event, meals, people)


# ── Lookups ──────────────────────────────────────────────────────────────────
def people_by_name(plan):
    return {p["name"]: p for p in plan["people"]}


def attendees(plan, meal):
    return [p["name"] for p in plan["people"] if meal in p["meals"]]


def seat_of(plan, meal, name):
    for t, table in enumerate(plan["seating"].get(meal, [])):
        if name in table:
            return t, table.index(name)
    return None


def table_pairs(table):
    n = len(table)
    if n < 2:
        return []
    if n == 2:
        return [pair(table[0], table[1])]
    return [pair(table[i], table[(i + 1) % n]) for i in range(n)]


def meal_pairs(plan, meal):
    return {p for table in plan["seating"].get(meal, []) for p in table_pairs(table)}


def other_meal_pair_index(plan, meal):
    """pair -> [other meals where they sat together] for this event."""
    idx = {}
    for m in plan["meals"]:
        if m == meal:
            continue
        for p in meal_pairs(plan, m):
            idx.setdefault(p, []).append(m)
    return idx


def history_pair_index(plan):
    idx = {}
    for h in plan.get("history", []):
        for a, b in h["pairs"]:
            idx.setdefault(pair(a, b), []).append(h["event"])
    return idx


def relation_pairs(plan):
    names = {p["name"] for p in plan["people"]}
    out = set()
    for p in plan["people"]:
        for r in p["relations"]:
            if r in names and r != p["name"]:
                out.add(pair(p["name"], r))
    return out


def preferred_pairs(plan):
    names = {p["name"] for p in plan["people"]}
    out = set()
    for p in plan["people"]:
        for r in p["preferred"]:
            if r in names and r != p["name"]:
                out.add(pair(p["name"], r))
    return out


def keep_apart_pairs(plan):
    return {pair(a, b) for a, b in plan.get("keep_apart", [])}


# ── Solving ──────────────────────────────────────────────────────────────────
def build_context(plan, other_meals):
    people = people_by_name(plan)
    weights = {}

    def add(p, w):
        weights[p] = weights.get(p, 0) + w

    for p in preferred_pairs(plan):
        add(p, W_PREFERRED)
    for p in relation_pairs(plan):
        add(p, W_RELATION)
    for p in keep_apart_pairs(plan):
        add(p, W_KEEP_APART)
    for p, events in history_pair_index(plan).items():
        add(p, W_PAST_EVENT * len(events))
    for m in other_meals:
        for p in meal_pairs(plan, m):
            add(p, W_REPEAT)
    return Context(
        sex={n: p["sex"] for n, p in people.items()},
        group={n: p.get("group", "") for n, p in people.items()},
        pair_weights=weights,
    )


def _locked_positions(plan, meal):
    out = {}
    for name in plan.get("locks", {}).get(meal, []):
        pos = seat_of(plan, meal, name)
        if pos:
            out[name] = pos
    return out


def sizes_for(plan, meal):
    names = attendees(plan, meal)
    sizes = plan["table_config"].get(meal) or [len(names)]
    return fit_sizes(sizes, len(names)) if names else []


def regenerate_meal(plan, meal, time_budget=None, seed=None):
    """Re-seat one meal around its locked guests, avoiding every other meal's pairs."""
    names = attendees(plan, meal)
    ctx = build_context(plan, [m for m in plan["meals"] if m != meal])
    plan["seating"][meal] = solve_meal(
        names, sizes_for(plan, meal), ctx,
        locked=_locked_positions(plan, meal), time_budget=time_budget, seed=seed,
    )
    _sync_config(plan, meal)


def regenerate_all(plan, time_budget=None, seed=None):
    """Re-seat every meal in order. Locked guests stay put; each meal avoids the
    pairs of the meals already seated in this run."""
    locked = {m: _locked_positions(plan, m) for m in plan["meals"]}
    done = []
    new = {}
    for i, meal in enumerate(plan["meals"]):
        saved = plan["seating"]
        plan["seating"] = new
        ctx = build_context(plan, done)
        plan["seating"] = saved
        new[meal] = solve_meal(
            attendees(plan, meal), sizes_for(plan, meal), ctx,
            locked=locked[meal], time_budget=time_budget,
            seed=None if seed is None else seed + i,
        )
        done.append(meal)
    plan["seating"] = new
    for meal in plan["meals"]:
        _sync_config(plan, meal)
    # Clean-up: earlier meals were seated without knowing later ones, so re-seat
    # any meal that still has a real problem now that every meal is known.
    for round_ in range(3):
        bad = [m for m in plan["meals"]
               if any(i["level"] != LOW for i in meal_issues(plan, m))]
        if not bad:
            break
        for k, meal in enumerate(bad):
            regenerate_meal(plan, meal, time_budget=time_budget,
                            seed=None if seed is None else seed + 100 * (round_ + 1) + k)


def _sync_config(plan, meal):
    plan["table_config"][meal] = [len(t) for t in plan["seating"].get(meal, [])]
    present = {n for t in plan["seating"].get(meal, []) for n in t}
    locks = plan.setdefault("locks", {})
    if meal in locks:
        locks[meal] = [n for n in locks[meal] if n in present]


# ── Checking a seating ───────────────────────────────────────────────────────
HIGH, MEDIUM, LOW = "high", "medium", "low"
LEVEL_SCORE = {HIGH: 100, MEDIUM: 30, LOW: 5}


def _join(items):
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


class Checker:
    """Precomputes everything needed to list a meal's problems quickly."""

    def __init__(self, plan, meal):
        self.meal = meal
        self.sex = {p["name"]: p["sex"] for p in plan["people"]}
        self.repeats = other_meal_pair_index(plan, meal)
        self.past = history_pair_index(plan)
        self.relations = relation_pairs(plan)
        self.keep_apart = keep_apart_pairs(plan)

    def pair_issues(self, a, b, t):
        out = []
        p = pair(a, b)
        if p in self.keep_apart:
            out.append((HIGH, "keep_apart", p, t, "on the keep-apart list"))
        if p in self.relations:
            out.append((HIGH, "relation", p, t, "listed as relations, so should be apart"))
        if p in self.repeats:
            out.append((HIGH, "repeat", p, t, f"also next to each other at {_join(self.repeats[p])}"))
        if p in self.past:
            out.append((MEDIUM, "past", p, t, f"sat together at {_join(self.past[p])}"))
        return out

    def same_sex_edges(self, tables):
        return sum(1 for t in tables for a, b in table_pairs(t)
                   if self.sex.get(a) and self.sex.get(a) == self.sex.get(b))

    def issues(self, tables):
        out = []
        for t, table in enumerate(tables):
            for a, b in table_pairs(table):
                out.extend(self.pair_issues(a, b, t))
            n = len(table)
            if n >= 3:
                for i in range(n):
                    left, cur, right = table[i - 1], table[i], table[(i + 1) % n]
                    s = self.sex.get(cur)
                    if s and s == self.sex.get(left) == self.sex.get(right):
                        word = "men" if s == "male" else "women"
                        out.append((LOW, "sandwich", (cur,), t, f"between two {word}"))
        return out


def issue_dict(issue):
    level, kind, names, t, text = issue
    who = " & ".join(names)
    return {"level": level, "kind": kind, "names": list(names), "table": t,
            "text": f"{who}: {text}"}


def meal_issues(plan, meal):
    checker = Checker(plan, meal)
    return [issue_dict(i) for i in checker.issues(plan["seating"].get(meal, []))]


def score(issues):
    return sum(LEVEL_SCORE[i[0]] for i in issues)


def swap_options(plan, meal, name):
    """For every other guest at this meal: what happens if `name` swaps with them.

    Returns {other: {"verdict": good|better|warn|bad|locked, "reason": str}}.
    """
    tables = plan["seating"].get(meal, [])
    here = seat_of(plan, meal, name)
    if not here:
        raise PlanError(f"{name} isn't seated at {meal}.")
    locks = set(plan.get("locks", {}).get(meal, []))
    checker = Checker(plan, meal)
    before = set(checker.issues(tables))
    base = score(before)
    base_edges = checker.same_sex_edges(tables)
    work = [list(t) for t in tables]
    t1, s1 = here
    out = {}
    for t2, table in enumerate(tables):
        for s2, other in enumerate(table):
            if other == name:
                continue
            if other in locks:
                out[other] = {"verdict": "locked", "reason": f"{other}'s seat is locked"}
                continue
            work[t1][s1], work[t2][s2] = other, name
            after = set(checker.issues(work))
            edges = checker.same_sex_edges(work) - base_edges
            work[t1][s1], work[t2][s2] = name, other
            new = sorted(after - before, key=lambda i: -LEVEL_SCORE[i[0]])
            delta = score(after) - base
            if any(i[0] == HIGH for i in new):
                verdict = "bad"
            elif any(i[0] == MEDIUM for i in new) or delta > 0 or edges > 0:
                verdict = "warn"
            elif delta < 0:
                verdict = "better"
            else:
                verdict = "good"
            if new:
                reason = issue_dict(new[0])["text"]
            elif edges > 0:
                reason = "puts two men or two women next to each other"
            else:
                reason = "fixes a problem" if delta < 0 else "no new problems"
            out[other] = {"verdict": verdict, "reason": reason}
    return out


# ── Edits ────────────────────────────────────────────────────────────────────
def _require_meal(plan, meal):
    if meal not in plan["seating"]:
        raise PlanError(f"No seating for '{meal}'.")


def swap(plan, meal, a, b):
    _require_meal(plan, meal)
    pa, pb = seat_of(plan, meal, a), seat_of(plan, meal, b)
    if not pa or not pb:
        raise PlanError("Both guests must be seated at this meal.")
    locks = set(plan.get("locks", {}).get(meal, []))
    if a in locks or b in locks:
        raise PlanError("Unlock a seat before moving that guest.")
    tables = plan["seating"][meal]
    tables[pa[0]][pa[1]], tables[pb[0]][pb[1]] = b, a


def set_lock(plan, meal, name, locked):
    _require_meal(plan, meal)
    if not seat_of(plan, meal, name):
        raise PlanError(f"{name} isn't seated at {meal}.")
    locks = plan.setdefault("locks", {}).setdefault(meal, [])
    if locked and name not in locks:
        locks.append(name)
    if not locked and name in locks:
        locks.remove(name)


def _clean_name(name):
    name = " ".join((name or "").split())
    if not name:
        raise PlanError("Please enter a name.")
    if "," in name:
        raise PlanError("Names can't contain commas.")
    if len(name) > 60:
        raise PlanError("That name is too long.")
    return name


def _clean_sex(sex):
    sex = tp.SEX_ALIASES.get((sex or "").strip().lower(), (sex or "").strip().lower())
    if sex not in ("male", "female"):
        raise PlanError("Please choose male or female.")
    return sex


def rename(plan, old, new, sex=None):
    people = people_by_name(plan)
    if old not in people:
        raise PlanError(f"Can't find {old}.")
    new = _clean_name(new)
    if new != old and new in people:
        raise PlanError(f"There's already a guest called {new}.")
    if sex:
        people[old]["sex"] = _clean_sex(sex)
    if new == old:
        return

    def sub(xs):
        return [new if x == old else x for x in xs]

    for p in plan["people"]:
        if p["name"] == old:
            p["name"] = new
        p["relations"] = sub(p["relations"])
        p["preferred"] = sub(p["preferred"])
    for meal, tables in plan["seating"].items():
        plan["seating"][meal] = [sub(t) for t in tables]
    for meal, names in plan.get("locks", {}).items():
        plan["locks"][meal] = sub(names)
    plan["keep_apart"] = [sub(p) for p in plan.get("keep_apart", [])]


def add_guest(plan, name, sex, meals, relations=(), preferred=()):
    name = _clean_name(name)
    if name in people_by_name(plan):
        raise PlanError(f"There's already a guest called {name}.")
    meals = [m for m in meals if m in plan["meals"]]
    if not meals:
        raise PlanError("Choose at least one meal.")
    plan["people"].append({
        "name": name, "sex": _clean_sex(sex), "group": "",
        "relations": [r for r in relations if r], "preferred": [p for p in preferred if p],
        "meals": meals,
    })
    for meal in meals:
        tables = plan["seating"].get(meal)
        if tables is None:
            continue  # not generated yet; it'll be included when it is
        if not tables:
            tables.append([])
        min(tables, key=len).append(name)
        _sync_config(plan, meal)


def remove_guest(plan, name, meal=None):
    """Remove from one meal (meal given) or from the whole event."""
    people = people_by_name(plan)
    if name not in people:
        raise PlanError(f"Can't find {name}.")
    meals = [meal] if meal else list(plan["meals"])
    for m in meals:
        if m in people[name]["meals"]:
            people[name]["meals"].remove(m)
        tables = plan["seating"].get(m)
        if tables:
            plan["seating"][m] = [[n for n in t if n != name] for t in tables]
            plan["seating"][m] = [t for t in plan["seating"][m] if t]
            _sync_config(plan, m)
    if meal is None:
        plan["people"] = [p for p in plan["people"] if p["name"] != name]
        for p in plan["people"]:
            p["relations"] = [r for r in p["relations"] if r != name]
            p["preferred"] = [r for r in p["preferred"] if r != name]
        plan["keep_apart"] = [kp for kp in plan.get("keep_apart", []) if name not in kp]


def add_keep_apart(plan, a, b):
    names = people_by_name(plan)
    if a not in names or b not in names:
        raise PlanError("Choose two guests.")
    if a == b:
        raise PlanError("Choose two different guests.")
    p = list(pair(a, b))
    if p not in [list(pair(*x)) for x in plan.setdefault("keep_apart", [])]:
        plan["keep_apart"].append(p)


def remove_keep_apart(plan, a, b):
    p = pair(a, b)
    plan["keep_apart"] = [x for x in plan.get("keep_apart", []) if pair(*x) != p]


# ── Past events ──────────────────────────────────────────────────────────────
def history_from_file(raw, filename):
    """Neighbour pairs from a previous event: a saved plan (.json) or the
    seating CSV export (Meal, Table, Seat, Name columns)."""
    text = raw.decode("utf-8-sig", errors="replace")
    base = (filename or "Previous event").rsplit(".", 1)[0].replace("_", " ")
    if text.lstrip().startswith("{"):
        try:
            other = load_plan(json.loads(text))
        except (ValueError, PlanError) as e:
            raise PlanError(f"That plan file couldn't be read ({e}).")
        pairs = set()
        for m in other["meals"]:
            pairs |= meal_pairs(other, m)
        return {"event": other["event"] or base, "pairs": sorted(list(p) for p in pairs)}

    rows = list(csv.DictReader(io.StringIO(text)))
    cols = {c.strip().lower(): c for c in (rows[0].keys() if rows else [])}
    if not {"meal", "table", "seat", "name"} <= set(cols):
        raise PlanError("Upload a saved plan (.json) or a seating CSV exported from this app.")
    seats = {}
    for r in rows:
        try:
            key = (r[cols["meal"]].strip(), r[cols["table"]].strip())
            seats.setdefault(key, []).append((int(r[cols["seat"]]), r[cols["name"]].strip()))
        except (ValueError, AttributeError):
            continue
    pairs = set()
    for seat_list in seats.values():
        pairs |= set(table_pairs([n for _, n in sorted(seat_list)]))
    if not pairs:
        raise PlanError("No seating found in that file.")
    return {"event": base, "pairs": sorted(list(p) for p in pairs)}


def add_history(plan, entry):
    hist = plan.setdefault("history", [])
    names = {h["event"] for h in hist}
    event, i = entry["event"], 2
    while event in names:
        event = f"{entry['event']} ({i})"
        i += 1
    hist.append({"event": event, "pairs": entry["pairs"]})
    return event


def remove_history(plan, event):
    plan["history"] = [h for h in plan.get("history", []) if h["event"] != event]


# ── Saving / opening ─────────────────────────────────────────────────────────
def export_plan(plan):
    out = {"format": PLAN_FORMAT, "version": PLAN_VERSION,
           "saved_at": time.strftime("%Y-%m-%d %H:%M")}
    out.update(plan)
    return out


def load_plan(data):
    """Validate a plan dict from a file or the browser. Returns a clean plan."""
    if not isinstance(data, dict) or data.get("format") != PLAN_FORMAT:
        raise PlanError("That isn't a Table Planner plan file.")
    try:
        meals = [str(m) for m in data["meals"]]
        people = []
        for p in data["people"]:
            people.append({
                "name": _clean_name(p["name"]), "sex": _clean_sex(p["sex"]),
                "group": str(p.get("group") or ""),
                "relations": [str(x) for x in p.get("relations", [])],
                "preferred": [str(x) for x in p.get("preferred", [])],
                "meals": [m for m in p.get("meals", []) if m in meals],
            })
        names = {p["name"] for p in people}
        if len(names) != len(people):
            raise PlanError("The plan has duplicate guest names.")
        plan = new_plan(str(data.get("event") or ""), meals, people)
        for meal, tables in (data.get("seating") or {}).items():
            if meal not in meals:
                continue
            clean = [[str(n) for n in t if str(n) in names] for t in tables]
            plan["seating"][meal] = [t for t in clean if t]
        for meal in plan["seating"]:
            _sync_config(plan, meal)
        for meal, sizes in (data.get("table_config") or {}).items():
            if meal in meals and meal not in plan["seating"]:
                plan["table_config"][meal] = [int(s) for s in sizes]
        plan["locks"] = {m: [n for n in ns if n in names]
                         for m, ns in (data.get("locks") or {}).items() if m in meals}
        plan["keep_apart"] = [list(pair(str(a), str(b))) for a, b in data.get("keep_apart", [])
                              if a in names and b in names and a != b]
        plan["history"] = [{"event": str(h["event"]), "pairs": [[str(a), str(b)] for a, b in h["pairs"]]}
                           for h in data.get("history", [])]
        return plan
    except (KeyError, TypeError, ValueError) as e:
        if isinstance(e, PlanError):
            raise
        raise PlanError("That plan file is damaged or incomplete.")


# ── Summaries ────────────────────────────────────────────────────────────────
def who_sits_where(plan):
    """[(name, {meal: (table_no, seat_no)})] sorted A–Z (1-based numbers)."""
    rows = []
    for p in sorted(plan["people"], key=lambda p: p["name"].lower()):
        where = {}
        for meal in plan["meals"]:
            pos = seat_of(plan, meal, p["name"])
            if pos:
                where[meal] = (pos[0] + 1, pos[1] + 1)
        rows.append((p["name"], where))
    return rows


def neighbour_summary(plan):
    """name -> {"neighbours": {other: [meals]}} across the event."""
    out = {p["name"]: {} for p in plan["people"]}
    for meal in plan["meals"]:
        for a, b in meal_pairs(plan, meal):
            out.setdefault(a, {}).setdefault(b, []).append(meal)
            out.setdefault(b, {}).setdefault(a, []).append(meal)
    return out
