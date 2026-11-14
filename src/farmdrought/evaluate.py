"""evaluate.py: score a set of alarms against what really happened.

Everything is scored with one cost rule:
    cost = MISS_COST x missed droughts + false alarms
A lower cost is better. Missing a drought counts 3 times as much as a false alarm.
"""
import numpy as np
from sklearn.metrics import roc_auc_score

from farmdrought.config import D2_CLASS, MISS_COST, SEASON_THRESHOLD


def tally(y, alarm, miss_cost=MISS_COST):
    """Count hits, misses and false alarms, and turn them into a cost.

    y     : the truth, 1 if severe drought really came, else 0
    alarm : True where a warning was given
    """
    y = np.asarray(y) == 1
    alarm = np.asarray(alarm, dtype=bool)
    caught = int((alarm & y).sum())         # warned, and drought came
    missed = int((~alarm & y).sum())        # no warning, but drought came
    false_alarms = int((alarm & ~y).sum())  # warned, but no drought came
    return {
        "cost": miss_cost * missed + false_alarms,
        "alarms": int(alarm.sum()),
        "caught": caught,
        "missed": missed,
        "false_alarms": false_alarms,
        # precision: of the warnings given, what share were right?
        "precision": round(float(caught / max(alarm.sum(), 1)), 3),
        # recall: of the droughts that came, what share did we warn about?
        "recall": round(float(caught / max(y.sum(), 1)), 3),
    }


def pick_threshold(score, y, miss_cost=MISS_COST):
    """Find the alarm threshold with the lowest cost: warn when score >= threshold.

    Tries 0.01, 0.02, ... up to 1.01 (which means "never warn") and keeps the cheapest.
    ONLY ever call this with validation rows, never with test rows.
    """
    candidates = np.arange(1, 102) / 100
    costs = [tally(y, score >= t, miss_cost)["cost"] for t in candidates]
    return float(candidates[int(np.argmin(costs))])


def events(rows, alarm_column):
    """Count drought onsets and how many of them we warned about in time.

    An onset "event" is a week when a county enters D2 after at least 8 weeks out of it.
    It counts as warned if there was an alarm in any of the 4 weeks before.
    The lead time is how many weeks before the onset the earliest of those alarms came.
    """
    n_events, n_warned, leads = 0, 0, []
    for _, county in rows.sort_values("date").groupby("fips"):
        cls = county["cls"].values
        alarm = county[alarm_column].values
        for i in range(8, len(cls)):
            if cls[i] >= D2_CLASS and (cls[i - 8 : i] < D2_CLASS).all():
                n_events += 1
                weeks_before = [j for j in range(1, 5) if alarm[i - j]]
                if weeks_before:
                    n_warned += 1
                    leads.append(max(weeks_before))
    return {
        "n": n_events,
        "warned_within_4_weeks": n_warned,
        "median_lead_weeks": float(np.median(leads)) if leads else 0.0,
    }


# ================================ 6-month outlook ================================

def season_costs(g, p_column="p_season"):
    """Cost of the model and of every simple rule, on one group of rows."""
    y = g["y_season"]
    return {
        "system": tally(y, g[p_column] >= SEASON_THRESHOLD)["cost"],
        "Persistence": tally(y, g["alarm_season_persistence"])["cost"],
        "D1 now": tally(y, g["alarm_season_d1"])["cost"],
        "Usual": tally(y, g["p_season_usual"] >= SEASON_THRESHOLD)["cost"],
        "Always warn": tally(y, np.ones(len(g), dtype=bool))["cost"],
        "Never warn": tally(y, np.zeros(len(g), dtype=bool))["cost"],
    }


def season_block(g, p_column="p_season"):
    """Results of the 6-month outlook on the Rio Grande rows."""
    y, p = g["y_season"], g[p_column]
    costs = season_costs(g, p_column)
    system = tally(y, p >= SEASON_THRESHOLD)
    # Brier score = average squared gap between the probability and what happened (lower
    # is better). Count the test years where the model's Brier score beats "usual".
    years = g.groupby(g["date"].dt.year)
    wins = sum(((yr[p_column] - yr["y_season"]) ** 2).mean() < ((yr["p_season_usual"] - yr["y_season"]) ** 2).mean()
               for _, yr in years)
    return {
        "rows": len(g), "base_rate": round(float(y.mean()), 3),
        "precision": system["precision"], "recall": system["recall"],
        "auc": round(roc_auc_score(y, p), 3),
        "system_cost": costs["system"], "persistence_cost": costs["Persistence"],
        "d1_rule_cost": costs["D1 now"], "usual_cost": costs["Usual"],
        "always_warn_cost": costs["Always warn"], "never_warn_cost": costs["Never warn"],
        "pct_cheaper_than_persistence": round(100 * (1 - costs["system"] / costs["Persistence"]), 1),
        "beats_every_baseline": bool(costs["system"] < min(v for k, v in costs.items() if k != "system")),
        "years_better_than_usual": f"{wins}/{years.ngroups}",
    }


def season_river(river, g):
    """6-month transfer test: the Rio Grande model on one river."""
    costs = season_costs(g)
    rules = {k: v for k, v in costs.items() if k != "system"}
    best = min(rules, key=rules.get)
    return {
        "river": river, "system_cost": costs["system"], "persistence_cost": costs["Persistence"],
        "best_rule": best, "best_rule_cost": rules[best],
        "pct_cheaper_than_best_rule": round(100 * (1 - costs["system"] / max(rules[best], 1)), 1),
        "own_river_cost": season_costs(g, "p_season_own")["system"],
    }


# ================================ 12-month outlook ================================

def mae(g, column):
    """Mean absolute error: on average, how many weeks off is this estimate?"""
    return round(float((g[column] - g["y_weeks"]).abs().mean()), 2)


YEAR_BASELINES = {"same as now": "weeks_same_as_now", "last year": "weeks_last_year", "usual": "weeks_usual"}


def year_block(g, column="weeks_model"):
    """Results of the 12-month outlook on the Rio Grande rows."""
    years = g.groupby(g["date"].dt.year)
    better = lambda base: sum(mae(yr, column) < mae(yr, base) for _, yr in years)
    return {
        "rows": len(g), "mean_weeks": round(float(g["y_weeks"].mean()), 1),
        "mae_system": mae(g, column), "mae_same_as_now": mae(g, "weeks_same_as_now"),
        "mae_last_year": mae(g, "weeks_last_year"), "mae_usual": mae(g, "weeks_usual"),
        "beats_every_baseline": bool(mae(g, column) < min(mae(g, c) for c in YEAR_BASELINES.values())),
        "years_better_than_last_year": f"{better('weeks_last_year')}/{years.ngroups}",
        "years_better_than_usual": f"{better('weeks_usual')}/{years.ngroups}",
    }


def year_river(river, g):
    """12-month transfer test: the Rio Grande model on one river."""
    errors = {name: mae(g, column) for name, column in YEAR_BASELINES.items()}
    best = min(errors, key=errors.get)
    return {"river": river, "mae_system": mae(g, "weeks_model"), "best_baseline": best,
            "mae_best_baseline": errors[best], "mae_own_river": mae(g, "weeks_own")}
