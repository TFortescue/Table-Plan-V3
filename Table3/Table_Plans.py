# Table_Plans.py (v3 - optimised)
# Reduced iterations, faster per-run, same quality output

import csv
import math
import argparse
import random

BONUS_PREFERRED           = -200
PENALTY_RELATION          = 120
PENALTY_SAME_SEX_EDGE     = 100
PENALTY_DOUBLE_SAME_SEX   = 2500
PENALTY_REPEAT_NEIGHBOUR  = 700
PENALTY_SAME_GROUP_EDGE   = 150
PENALTY_SAME_GROUP_CHAIN  = 600
PENALTY_SAME_SEX_CHAIN    = 1200
PENALTY_SAME_SEX_LOAD     = 120


class Person:
    def __init__(self, pid, name, sex, relations, preferred, meals, group=None):
        sex = sex.lower().strip()
        if sex not in ("male", "female"):
            raise ValueError(f"Invalid sex '{sex}' for '{name}', must be male/female.")
        self.id = pid
        self.name = name
        self.sex = sex
        self.group = group or ""
        self.relations = list(relations)
        self.relation_set = set(relations)
        self.preferred = list(preferred)
        self.preferred_set = set(preferred)
        self.meals = list(meals)

    def __repr__(self):
        return f"Person(name={self.name!r}, sex={self.sex!r})"

    def is_related_to(self, other):
        return other.name in self.relation_set

    def prefers(self, other):
        return other.name in self.preferred_set


def read_people_from_csv(filename):
    people = []
    required_headers = ["name", "sex", "relations", "preferred people"]
    try:
        with open(filename, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            if not headers:
                return []
            missing = [h for h in required_headers if h not in headers]
            if missing:
                return []
            has_id = "id" in headers
            has_group = "group" in headers
            try:
                pref_idx = headers.index("preferred people")
                meal_cols = headers[pref_idx + 1:]
            except ValueError:
                return []
            for line_num, row in enumerate(reader, start=2):
                try:
                    name = (row.get("name") or "").strip()
                    sex = (row.get("sex") or "").strip()
                    if not name or not sex:
                        continue
                    pid = (row.get("id") or name).strip() if has_id else name
                    group = (row.get("group") or "").strip() if has_group else ""
                    rel_str = row.get("relations") or ""
                    pref_str = row.get("preferred people") or ""
                    relations = [r.strip() for r in rel_str.split(",") if r.strip()]
                    preferred = [p.strip() for p in pref_str.split(",") if p.strip()]
                    meals = []
                    for col in meal_cols:
                        meal_name = col.strip()
                        if meal_name and (row.get(col) or "").strip().lower() == "yes":
                            meals.append(meal_name)
                    people.append(Person(pid=pid, name=name, sex=sex,
                                        relations=relations, preferred=preferred,
                                        meals=meals, group=group))
                except Exception:
                    continue
    except Exception:
        return []
    return people


def read_meals_from_csv(filename):
    try:
        with open(filename, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if not header:
                return []
            try:
                pref_idx = header.index("preferred people")
            except ValueError:
                return []
            meal_cols = header[pref_idx + 1:]
            return [c.strip() for c in meal_cols if c.strip()]
    except Exception:
        return []


def validate_people(people):
    errors = []
    seen = set()
    for p in people:
        if p.name in seen:
            errors.append(f"Duplicate name '{p.name}'.")
        seen.add(p.name)
    names = {p.name for p in people}
    for p in people:
        if p.name in p.relation_set:
            errors.append(f"{p.name} cannot list themselves in relations.")
        if p.name in p.preferred_set:
            errors.append(f"{p.name} cannot prefer themselves.")
        if len(p.relations) != len(p.relation_set):
            errors.append(f"{p.name} has duplicate entries in relations.")
        if len(p.preferred) != len(p.preferred_set):
            errors.append(f"{p.name} has duplicate entries in preferred people.")
        for r in p.relations:
            if r and r not in names:
                errors.append(f"'{p.name}' lists relation '{r}', which is not in file.")
        for pref in p.preferred:
            if pref and pref not in names:
                errors.append(f"'{p.name}' prefers '{pref}', which is not in file.")
    return errors


def canonical_pair(name1, name2):
    return (name1, name2) if name1 < name2 else (name2, name1)


def compute_arrangement_penalty(arrangement, seated_pairs_history=None):
    if seated_pairs_history is None:
        seated_pairs_history = set()
    n = len(arrangement)
    if n == 0:
        return 0.0

    male_cnt = sum(1 for p in arrangement if p.sex == "male")
    imbalance_ratio = abs(male_cnt - (n - male_cnt)) / max(1, n)

    if imbalance_ratio < 0.15:
        single_sex_weight, double_sex_weight = 1.6, 1.0
    elif imbalance_ratio < 0.35:
        single_sex_weight, double_sex_weight = 1.1, 1.1
    else:
        single_sex_weight, double_sex_weight = 0.7, 1.3

    penalty = 0.0
    same_sex_counts = {}

    for i in range(n):
        a = arrangement[i]
        b = arrangement[(i + 1) % n]
        pair = canonical_pair(a.name, b.name)
        if pair in seated_pairs_history:
            penalty += PENALTY_REPEAT_NEIGHBOUR
        if a.is_related_to(b) or b.is_related_to(a):
            penalty += PENALTY_RELATION
        if a.sex == b.sex:
            penalty += PENALTY_SAME_SEX_EDGE * single_sex_weight
            same_sex_counts[a.name] = same_sex_counts.get(a.name, 0) + 1
            same_sex_counts[b.name] = same_sex_counts.get(b.name, 0) + 1
        ga, gb = a.group or "", b.group or ""
        if ga and gb and ga == gb:
            penalty += PENALTY_SAME_GROUP_EDGE
        if a.prefers(b) or b.prefers(a):
            penalty += BONUS_PREFERRED

    for i in range(n):
        cur = arrangement[i]
        left = arrangement[(i - 1) % n]
        right = arrangement[(i + 1) % n]
        if cur.sex == left.sex == right.sex:
            penalty += PENALTY_DOUBLE_SAME_SEX * double_sex_weight + PENALTY_SAME_SEX_CHAIN
        gcur, gleft, gright = cur.group or "", left.group or "", right.group or ""
        if gcur and gleft and gright and gcur == gleft == gright:
            penalty += PENALTY_SAME_GROUP_CHAIN

    for count in same_sex_counts.values():
        if count > 1:
            penalty += PENALTY_SAME_SEX_LOAD * (count - 1)

    return penalty


def violates_sex_sandwich(arrangement):
    n = len(arrangement)
    if n < 3:
        return False
    for i in range(n):
        if arrangement[i].sex == arrangement[(i-1)%n].sex == arrangement[(i+1)%n].sex:
            return True
    return False


def solve_circle_anneal(people, seated_pairs_history=None,
                        max_iters_per_person=2500,
                        start_temp=8.0, end_temp=0.05):
    if seated_pairs_history is None:
        seated_pairs_history = set()
    n = len(people)
    if n <= 2:
        return list(people)

    current = list(people)
    random.shuffle(current)
    current_pen = compute_arrangement_penalty(current, seated_pairs_history)
    best = list(current)
    best_pen = current_pen

    size_scale = min(2.0, 1.0 + max(0, n - 12) / 20.0)
    max_iters = int(max_iters_per_person * n * size_scale)
    log_ratio = math.log(end_temp / max(start_temp, 1e-9))

    for it in range(1, max_iters + 1):
        temp = start_temp * math.exp(log_ratio * it / max_iters)
        move_type = random.random()

        if move_type < 0.6:
            i, j = random.randrange(n), random.randrange(n)
            if i == j:
                continue
            current[i], current[j] = current[j], current[i]
            if violates_sex_sandwich(current):
                current[i], current[j] = current[j], current[i]
                continue
            new_pen = compute_arrangement_penalty(current, seated_pairs_history)
            delta = new_pen - current_pen
            if delta <= 0 or math.exp(-delta / max(temp, 1e-9)) > random.random():
                current_pen = new_pen
                if new_pen < best_pen:
                    best_pen, best = new_pen, list(current)
            else:
                current[i], current[j] = current[j], current[i]

        elif move_type < 0.85:
            i, j = sorted(random.sample(range(n), 2))
            current[i:j+1] = reversed(current[i:j+1])
            if violates_sex_sandwich(current):
                current[i:j+1] = reversed(current[i:j+1])
                continue
            new_pen = compute_arrangement_penalty(current, seated_pairs_history)
            delta = new_pen - current_pen
            if delta <= 0 or math.exp(-delta / max(temp, 1e-9)) > random.random():
                current_pen = new_pen
                if new_pen < best_pen:
                    best_pen, best = new_pen, list(current)
            else:
                current[i:j+1] = reversed(current[i:j+1])

        else:
            a, b, c = random.sample(range(n), 3)
            tmp = current[a]
            current[a] = current[c]; current[c] = current[b]; current[b] = tmp
            if violates_sex_sandwich(current):
                current[b] = current[c]; current[c] = current[a]; current[a] = tmp
                continue
            new_pen = compute_arrangement_penalty(current, seated_pairs_history)
            delta = new_pen - current_pen
            if delta <= 0 or math.exp(-delta / max(temp, 1e-9)) > random.random():
                current_pen = new_pen
                if new_pen < best_pen:
                    best_pen, best = new_pen, list(current)
            else:
                tmp2 = current[b]; current[b] = current[c]; current[c] = current[a]; current[a] = tmp2

    # Limited hill-climb polish
    improved = True
    while improved:
        improved = False
        indices = list(range(n))
        random.shuffle(indices)
        for ii in range(min(len(indices), 15)):
            i = indices[ii]
            for jj in range(ii + 1, min(len(indices), 15)):
                j = indices[jj]
                best[i], best[j] = best[j], best[i]
                if violates_sex_sandwich(best):
                    best[i], best[j] = best[j], best[i]
                    continue
                pen = compute_arrangement_penalty(best, seated_pairs_history)
                if pen + 1e-8 < best_pen:
                    best_pen = pen
                    improved = True
                else:
                    best[i], best[j] = best[j], best[i]
            if improved:
                break

    return best


def best_arrangement_for_group(people, seated_pairs_history=None, runs=3):
    if seated_pairs_history is None:
        seated_pairs_history = set()
    best_arr = None
    best_pen = float("inf")
    if len(people) > 20:
        runs = max(runs, 4)
    for _ in range(runs):
        arr = solve_circle_anneal(list(people), seated_pairs_history)
        pen = compute_arrangement_penalty(arr, seated_pairs_history)
        if pen < best_pen - 1e-8:
            best_arr = arr
            best_pen = pen
    return best_arr


def _find_arrangement_backtrack(
    current_arrangement, remaining_people, total_people_to_seat,
    arrangements_already_found_for_this_meal, seated_neighbour_pairs_overall,
    sex_violation_already_used_up, options=None,
):
    people_list = list(remaining_people)
    arrangement = best_arrangement_for_group(
        people_list, seated_pairs_history=seated_neighbour_pairs_overall, runs=3)
    if len(arrangement) != total_people_to_seat:
        arrangement = people_list
    return arrangement


def seat_people(all_people_info, meal_names_list):
    final = {}
    seated_pairs_history = set()
    for meal in meal_names_list:
        attendees = [p for p in all_people_info if meal in p.meals]
        n = len(attendees)
        if n == 0:
            final[meal] = []
        elif n == 1:
            final[meal] = [[attendees[0]]]
        else:
            arrangement = best_arrangement_for_group(attendees, seated_pairs_history, runs=5)
            final.setdefault(meal, []).append(arrangement)
            for i in range(len(arrangement)):
                a = arrangement[i].name
                b = arrangement[(i + 1) % len(arrangement)].name
                seated_pairs_history.add(canonical_pair(a, b))
    return final


def draw_text_table(arrangement_list, grid_width=60, grid_height=25):
    num_people = len(arrangement_list)
    if num_people == 0:
        return
    grid = [[" " for _ in range(grid_width)] for _ in range(grid_height)]
    cx, cy = grid_width // 2, grid_height // 2
    rx, ry = (grid_width // 2) * 0.8, (grid_height // 2) * 0.7
    for i, p in enumerate(arrangement_list):
        angle = (2 * math.pi * i / num_people) - (math.pi / 2)
        x = max(0, min(grid_width-1, int(round(cx + rx * math.cos(angle)))))
        y = max(0, min(grid_height-1, int(round(cy + ry * math.sin(angle)))))
        label = f"{i+1}:{p.name[:6]}"
        start = max(0, x - len(label) // 2)
        label = label[:max(0, grid_width - start)]
        free = start + len(label) <= grid_width and all(grid[y][start+k] == " " for k in range(len(label)))
        if free:
            for k, ch in enumerate(label):
                grid[y][start + k] = ch
        elif grid[y][x] == " ":
            grid[y][x] = "*"
    border = "+" + "-" * (grid_width - 2) + "+"
    print(border)
    for row in grid:
        print("|" + "".join(row[1:-1]) + "|")
    print(border)


def visualize_seating(all_meal_arrangements):
    print("\n--- Final Seating Arrangements ---")
    shown_pairs = set()
    for meal, arr_list in all_meal_arrangements.items():
        print(f"\nMeal '{meal}':")
        if not arr_list:
            print("  No arrangement.")
            continue
        arr = arr_list[-1]
        n = len(arr)
        if n == 1:
            print(f"  Only {arr[0].name} is attending.")
            continue
        for i in range(n):
            a, b = arr[i], arr[(i+1) % n]
            pair = canonical_pair(a.name, b.name)
            flags = ""
            if a.is_related_to(b) or b.is_related_to(a): flags += " (R!)"
            if a.prefers(b) or b.prefers(a): flags += " (P*)"
            if a.sex == b.sex: flags += " (S!)"
            if pair in shown_pairs: flags += " (N!)"
            print(f"    Seat {i+1}: {a.name} ({a.sex}){flags} -> {b.name} ({b.sex})")
            shown_pairs.add(pair)
        draw_text_table(arr)


def save_plans_to_file(all_meal_arrangements, filename):
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write("--- Seating Arrangements ---\n\n")
            for meal, arr_list in all_meal_arrangements.items():
                f.write(f"Meal '{meal}':\n")
                if not arr_list:
                    f.write("  No arrangement.\n\n")
                    continue
                arr = arr_list[-1]
                n = len(arr)
                if n == 1:
                    f.write(f"  Only {arr[0].name} is attending.\n\n")
                    continue
                for i in range(n):
                    a, b = arr[i], arr[(i+1)%n]
                    f.write(f"  Seat {i+1}: {a.name} ({a.sex}) -> Seat {(i+1)%n+1}: {b.name} ({b.sex})\n")
                f.write("\n")
    except Exception as e:
        print(f"[ERROR] Could not save plans: {e}")


def parse_args():
    parser = argparse.ArgumentParser(description="Circular seating plan generator")
    parser.add_argument("csv_file", nargs="?")
    parser.add_argument("-o", "--output")
    parser.add_argument("--version", action="version", version="Table Plan Generator 3.0")
    return parser.parse_args()


def main():
    args = parse_args()
    csv_name = args.csv_file or input("Enter CSV filename: ").strip()
    if not csv_name:
        print("[ERROR] No CSV filename provided.")
        return
    people = read_people_from_csv(csv_name)
    if not people:
        print("[ERROR] No people loaded from CSV.")
        return
    errors = validate_people(people)
    if errors:
        for e in errors:
            print("  -", e)
        return
    meals = read_meals_from_csv(csv_name)
    arrangements = seat_people(people, meals)
    visualize_seating(arrangements)
    if args.output:
        save_plans_to_file(arrangements, args.output)


if __name__ == "__main__":
    main()
