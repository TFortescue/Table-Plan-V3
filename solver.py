"""Meal-level seating solver.

Optimises every table of a meal at once with simulated annealing, so guests can
move between tables as well as around them. Supports locked seats and weighted
"avoid" / "prefer" pairs (repeat neighbours, keep-apart, relations, past events).

Seating is represented as plain names: a meal is a list of tables, a table is a
list of names in seat order (seat 1 first, clockwise, circular).
"""

import math
import random
import time

# ── Weights (higher = worse; negative = good) ────────────────────────────────
W_KEEP_APART = 6000       # explicit "never seat together"
W_RELATION = 1500         # listed in each other's relations column
W_REPEAT = 900            # neighbours at another meal this event (per meal)
W_PAST_EVENT = 350        # neighbours at a previous event (per event)
W_PREFERRED = -200        # someone asked to sit next to them

W_SAME_SEX_EDGE = 100
W_SAME_SEX_TRIPLE = 3700  # someone with the same sex on both sides
W_SAME_SEX_LOAD = 120     # spread unavoidable same-sex edges across people
W_SAME_GROUP_EDGE = 150
W_SAME_GROUP_TRIPLE = 600


def pair(a, b):
    return (a, b) if a < b else (b, a)


class Context:
    """Everything the scorer needs to know about guests and pair preferences."""

    def __init__(self, sex, group=None, pair_weights=None):
        self.sex = sex                      # name -> "male"/"female"
        self.group = group or {}            # name -> group string ("" = none)
        self.pair_weights = pair_weights or {}  # (a, b) sorted -> weight

    def edge(self, a, b):
        return self.pair_weights.get(pair(a, b), 0)


def table_penalty(table, ctx):
    n = len(table)
    if n < 2:
        return 0.0
    sex, group, pw = ctx.sex, ctx.group, ctx.pair_weights
    males = sum(1 for p in table if sex.get(p) == "male")
    imbalance = abs(2 * males - n) / n
    if imbalance < 0.15:
        edge_w, triple_w = 1.6, 1.0
    elif imbalance < 0.35:
        edge_w, triple_w = 1.1, 1.1
    else:
        edge_w, triple_w = 0.7, 1.3

    total = 0.0
    load = {}
    for i in range(n):
        a = table[i]
        b = table[(i + 1) % n]
        if n == 2 and i == 1:
            break  # two people share a single edge
        total += pw.get((a, b) if a < b else (b, a), 0)
        if sex.get(a) == sex.get(b):
            total += W_SAME_SEX_EDGE * edge_w
            load[a] = load.get(a, 0) + 1
            load[b] = load.get(b, 0) + 1
        ga, gb = group.get(a, ""), group.get(b, "")
        if ga and ga == gb:
            total += W_SAME_GROUP_EDGE
    if n >= 3:
        for i in range(n):
            left, cur, right = table[i - 1], table[i], table[(i + 1) % n]
            if sex.get(left) == sex.get(cur) == sex.get(right):
                total += W_SAME_SEX_TRIPLE * triple_w
            g = group.get(cur, "")
            if g and g == group.get(left, "") == group.get(right, ""):
                total += W_SAME_GROUP_TRIPLE
    for c in load.values():
        if c > 1:
            total += W_SAME_SEX_LOAD * (c - 1)
    return total


def meal_penalty(tables, ctx):
    return sum(table_penalty(t, ctx) for t in tables)


def fit_sizes(sizes, n_people):
    """Make table sizes add up to the number of guests (after late additions or
    removals): grow the smallest tables / shrink the largest, one seat at a time."""
    sizes = [s for s in sizes if s > 0] or [n_people]
    sizes = list(sizes)
    while sum(sizes) < n_people:
        sizes[sizes.index(min(sizes))] += 1
    while sum(sizes) > n_people:
        i = sizes.index(max(sizes))
        sizes[i] -= 1
        if sizes[i] == 0:
            sizes.pop(i)
    return sizes


def solve_meal(attendees, sizes, ctx, locked=None, time_budget=None, seed=None):
    """Seat `attendees` (names) at tables of `sizes`.

    locked: {name: (table_index, seat_index)} — those guests stay exactly there.
    Returns a list of tables (lists of names).
    """
    rng = random.Random(seed)
    attendees = list(dict.fromkeys(attendees))
    if not attendees:
        return []
    sizes = fit_sizes(sizes, len(attendees))
    tables = [[None] * s for s in sizes]

    fixed = set()
    for name, (t, s) in (locked or {}).items():
        if name in attendees and 0 <= t < len(tables) and 0 <= s < len(tables[t]) and tables[t][s] is None:
            tables[t][s] = name
            fixed.add((t, s))
    placed = {tables[t][s] for t, s in fixed}

    free_people = [p for p in attendees if p not in placed]
    rng.shuffle(free_people)
    free_pos = [(t, s) for t in range(len(tables)) for s in range(len(tables[t])) if (t, s) not in fixed]
    # Fill free seats alternating sexes where possible for a decent start.
    men = [p for p in free_people if ctx.sex.get(p) == "male"]
    women = [p for p in free_people if ctx.sex.get(p) != "male"]
    order = []
    while men or women:
        if women and (not men or len(women) >= len(men)):
            order.append(women.pop())
        if men:
            order.append(men.pop())
    for (t, s), p in zip(free_pos, order):
        tables[t][s] = p

    if len(free_pos) < 2:
        return tables

    n = len(attendees)
    if time_budget is None:
        time_budget = min(3.0, 0.4 + 0.05 * n)

    pens = [table_penalty(t, ctx) for t in tables]
    cur = sum(pens)
    best, best_tables = cur, [list(t) for t in tables]

    # Positions grouped per table for in-table segment reversals
    free_by_table = {}
    for t, s in free_pos:
        free_by_table.setdefault(t, []).append(s)

    t_start, t_end = 400.0, 1.0
    log_ratio = math.log(t_end / t_start)
    start = time.perf_counter()
    it = 0
    temp = t_start
    while True:
        it += 1
        if it & 255 == 0:
            frac = (time.perf_counter() - start) / time_budget
            if frac >= 1:
                break
            temp = t_start * math.exp(log_ratio * frac)

        r = rng.random()
        if r < 0.75:
            (t1, s1), (t2, s2) = rng.sample(free_pos, 2)
            tables[t1][s1], tables[t2][s2] = tables[t2][s2], tables[t1][s1]
            touched = {t1, t2}

            def undo():
                tables[t1][s1], tables[t2][s2] = tables[t2][s2], tables[t1][s1]
        elif r < 0.9 and len(free_pos) >= 3:
            (t1, s1), (t2, s2), (t3, s3) = rng.sample(free_pos, 3)
            a, b, c = tables[t1][s1], tables[t2][s2], tables[t3][s3]
            tables[t1][s1], tables[t2][s2], tables[t3][s3] = c, a, b
            touched = {t1, t2, t3}

            def undo():
                tables[t1][s1], tables[t2][s2], tables[t3][s3] = a, b, c
        else:
            t1 = rng.choice(list(free_by_table))
            seats = free_by_table[t1]
            if len(seats) < 3:
                continue
            i, j = sorted(rng.sample(range(len(seats)), 2))
            idx = seats[i:j + 1]
            vals = [tables[t1][k] for k in idx]
            for k, v in zip(idx, reversed(vals)):
                tables[t1][k] = v
            touched = {t1}

            def undo():
                for k, v in zip(idx, vals):
                    tables[t1][k] = v

        new_pens = {t: table_penalty(tables[t], ctx) for t in touched}
        delta = sum(new_pens[t] - pens[t] for t in touched)
        if delta <= 0 or rng.random() < math.exp(-delta / temp):
            for t, p in new_pens.items():
                pens[t] = p
            cur += delta
            if cur < best - 1e-9:
                best = cur
                best_tables = [list(t) for t in tables]
        else:
            undo()

    return best_tables
