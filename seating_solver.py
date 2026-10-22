# seating_solver.py (v3)
# Fixes variant seeding: variants of the SAME meal are independent,
# only cross-meal history is shared.

import random
from Table_Plans import _find_arrangement_backtrack, best_arrangement_for_group
from collections import OrderedDict


def split_into_tables(people, table_sizes):
    people = list(people)
    if not people:
        return []
    males = [p for p in people if getattr(p, "sex", "").lower() == "male"]
    females = [p for p in people if getattr(p, "sex", "").lower() == "female"]
    random.shuffle(males)
    random.shuffle(females)
    total = len(people)
    male_ratio = len(males) / total if total else 0.0
    assigned_tables = []

    for size in table_sizes:
        target_males = round(size * male_ratio)
        take_males = min(len(males), target_males)
        take_females = min(len(females), size - take_males)
        if take_males + take_females < size:
            remaining = size - (take_males + take_females)
            extra_m = min(remaining, len(males) - take_males)
            take_males += extra_m
            remaining -= extra_m
            take_females += min(remaining, len(females) - take_females)
        table_group = [males.pop() for _ in range(take_males)] + [females.pop() for _ in range(take_females)]
        random.shuffle(table_group)
        assigned_tables.append(table_group)

    leftovers = males + females
    for idx, p in enumerate(leftovers):
        assigned_tables[idx % len(assigned_tables)].append(p)

    return assigned_tables


def solve_single_meal(people, table_sizes, global_pairs=None):
    """
    Solve seating for ONE meal across multiple tables.
    global_pairs: neighbour pairs from OTHER meals (not mutated here; caller updates it).
    Returns list of tables (each table = list[Person]).
    """
    if global_pairs is None:
        global_pairs = set()

    results = []
    tables = split_into_tables(people, table_sizes)

    for table_group in tables:
        n = len(table_group)
        if n <= 1:
            results.append(table_group)
            continue

        arrangement = best_arrangement_for_group(
            table_group,
            seated_pairs_history=global_pairs,  # read-only context, not mutated
            runs=3,
        )
        if not arrangement:
            arrangement = table_group

        results.append(arrangement)

    return results


def solve_multiple_variants(people, meals, table_config, variants=1):
    """
    For each meal, generate `variants` alternative seating layouts.
    Each variant for a given meal is solved independently (no cross-variant pollution).
    Cross-meal history is accumulated from the FIRST variant of each meal.

    Returns: dict[meal] = [ [table1, table2, ...], ... ]  (one entry per variant)
    """
    final_output = {}
    # Cross-meal neighbour history — accumulated from first variant of each meal
    global_pairs_across_meals = set()

    for meal in meals:
        attendees = [p for p in people if meal in p.meals]
        sizes = table_config.get(meal, [])
        if not sizes:
            sizes = [len(attendees)] if attendees else []

        meal_variants = []

        for v_idx in range(variants):
            # Each variant sees cross-meal history but NOT history from sibling variants
            solution = solve_single_meal(attendees, sizes,
                                         global_pairs=set(global_pairs_across_meals))
            meal_variants.append(solution)

        final_output[meal] = meal_variants

        # Accumulate from first variant only so we don't over-restrict future meals
        first_variant = meal_variants[0] if meal_variants else []
        for table in first_variant:
            n = len(table)
            for i in range(n):
                a = table[i].name
                b = table[(i + 1) % n].name
                global_pairs_across_meals.add(tuple(sorted((a, b))))

    return final_output
