"""round3.py: score the round-3 additions ONCE and write one file per item.

ADDED in round 3 (ARCHITECTURE.md section 3). Version 1 is not changed by this file and stays
the reported system. Everything written here carries "added": true.

It runs the same two calls evaluate() makes (run_alert and run_outlook, seed 0, weeks up to
config.SCORE_THROUGH) and then only RE-SCORES what they produced:

  intervals_v1.json    year-block intervals around version 1's system-minus-rule differences
  trigger_annual.json  the trigger test with one decision per county per year (March), with the
                       two added rules, and intervals for the forecast's value minus each rule's
  calibration.json     the 6-month probability, raw and adjusted from past years only
  allocation.json      the budget-ranking backtest

The files go to reports/frozen/round3/. A file that exists is never replaced unless --force is
given: each item is declared in reports/decision.md and scored once.

THE YEAR. Every per-year number is grouped by the calendar year of the ISSUE date (the date the
forecast was made), all counties together. Every interval is a year-block bootstrap
(uncertainty.py: 10,000 draws, seed 0). Print n_years and the caveat beside each one.

Run it with:  PYTHONPATH=src python -m farmdrought.round3
              PYTHONPATH=src python -m farmdrought.round3 --force   (replace existing files)
"""
import json
import sys
from datetime import datetime

import numpy as np
import pandas as pd

from farmdrought.alert import run_alert, split_masks
from farmdrought.allocation import run_allocation
from farmdrought.baselines import BASELINES
from farmdrought.config import (COST_RATIOS, D2_CLASS, FOCUS_RIVER, FROZEN, MANIFEST, ROOT, ROUND3, SCORE_THROUGH,
                                SEASON_THRESHOLD, SEASON_WEEKS)
from farmdrought.evaluate import tally
from farmdrought.export import git_state
from farmdrought.manifest import check_manifest, sha256_of
from farmdrought.outlook import FEATURES_SEASON, chain, issue_rows, make_classifier, run_outlook
from farmdrought.prob_calibration import (brier, calibrate_by_past, calibration_coverage, class_frequency_by_past,
                                          reliability)
from farmdrought.trigger import annual_fires, annual_rows, run_trigger_annual
from farmdrought.uncertainty import direction, year_block_bootstrap
from farmdrought.v2 import SELECT_START

DRAWS, SEED = 10000, 0     # as declared in reports/decision.md
DECLARED_IN = ('reports/decision.md, section "Evaluation round 3 (written Nov 15, 2026, before any item below '
               'was scored)"')
YEAR_UNIT = "the calendar year of the issue date (the date the forecast was made), all counties together"
PICKED_AFTER = ("This rule was picked AFTER seeing every rule's result on these same rows (it is the one with the "
                "lowest total cost), so this comparison is harder for the system than a comparison with a rule "
                "named in advance.")
WORDS = {"a better": "{a} better", "b better": "{b} better", "not separated": "not separated"}


# ---------------------------------------------------------------------------------------------
# Small tools
# ---------------------------------------------------------------------------------------------
def by_year(rows, score):
    """One number per issue year: score(the rows of that year)."""
    return pd.Series({int(year): score(group) for year, group in rows.groupby(rows["date"].dt.year)})


def interval(a, b, weights, lower_is_better, a_name, b_name, block):
    """One year-block interval for A minus B, with the winner in words."""
    result = year_block_bootstrap(a, b, weights=weights, draws=DRAWS, seed=SEED, block=block,
                                  lower_is_better=lower_is_better)
    result["direction"] = WORDS[direction(result)].format(a=a_name, b=b_name)
    return result


def compare(name, a, b, weights, lower_is_better, rows_used, a_name="system", b_name="rule", note=None):
    """One comparison, A minus B: the per-year values, and an interval with single years (block 1)
    and with adjacent pairs of years (block 2, only when the number of years is even).

    a, b    : one number per issue year (a yearly total when weights is None, a yearly mean otherwise)
    weights : None, or the number of rows per year
    """
    out = {
        "name": name, "a": a_name, "b": b_name, "rows_used": rows_used, "year_unit": YEAR_UNIT,
        "statistic": "sum of the yearly totals" if weights is None else "mean over rows (yearly means weighted by rows)",
        "lower_is_better": bool(lower_is_better),
        "per_year": {"years": [int(y) for y in a.index], a_name: [float(v) for v in a], b_name: [float(v) for v in b],
                     **({} if weights is None else {"rows": [int(v) for v in weights]})},
        "block1": interval(a, b, weights, lower_is_better, a_name, b_name, 1),
        "block2": (interval(a, b, weights, lower_is_better, a_name, b_name, 2) if len(a) % 2 == 0
                   else "not computed: block 2 needs an even number of years"),
    }
    if weights is None:
        out[f"{a_name}_total"], out[f"{b_name}_total"] = float(a.sum()), float(b.sum())
    else:
        total = float(weights.sum())
        out[f"{a_name}_mean"], out[f"{b_name}_mean"] = float((a * weights).sum() / total), float((b * weights).sum() / total)
    out["difference"] = out["block1"]["diff"]
    if note:
        out["note"] = note
    return out


def cost_by_year(rows, label, alarm):
    """The cost rule (3 x missed + false alarms) per issue year. alarm: a column name or a function of the rows."""
    fires = (lambda g: g[alarm]) if isinstance(alarm, str) else alarm
    return by_year(rows, lambda g: tally(g[label], fires(g))["cost"])


# ---------------------------------------------------------------------------------------------
# Item 1: intervals around version 1's comparisons
# ---------------------------------------------------------------------------------------------
def alert_comparisons(rows, rows_used, picked, picked_words):
    """4-week alert: system cost minus each baseline's cost, then minus the baseline in `picked`.

    rows   : Rio Grande test rows of the 4-week alert (with the alarm columns)
    picked : the name of the rule singled out after the fact (the cheapest, or the best onset rule)
    """
    system = cost_by_year(rows, "y", "alarm_system")
    out = [compare(f"4-week system cost minus {name}", system, cost_by_year(rows, "y", column), None, True, rows_used,
                   b_name=name) for column, name in BASELINES.items()]
    column = next(c for c, name in BASELINES.items() if name == picked)
    out.append(compare(f"4-week system cost minus {picked_words} ({picked})", system, cost_by_year(rows, "y", column),
                       None, True, rows_used, b_name=picked, note=PICKED_AFTER))
    return out


def season_comparisons(rg):
    """6-month outlook: system cost minus each of the five simple rules' costs. rg: scored Rio Grande rows."""
    used = "scored Rio Grande outlook rows (issued monthly, test years, full 52-week future known)"
    rules = {
        "Persistence": "alarm_season_persistence",
        "D1 now": "alarm_season_d1",
        "Usual": lambda g: g["p_season_usual"] >= SEASON_THRESHOLD,
        "Always warn": lambda g: np.ones(len(g), dtype=bool),
        "Never warn": lambda g: np.zeros(len(g), dtype=bool),
    }
    system = cost_by_year(rg, "y_season", lambda g: g["p_season"] >= SEASON_THRESHOLD)
    return [compare(f"6-month system cost minus {name}", system, cost_by_year(rg, "y_season", alarm), None, True, used,
                    b_name=name) for name, alarm in rules.items()]


def year_comparisons(rg):
    """12-month outlook: the system's mean absolute error minus each baseline's. rg: scored Rio Grande rows."""
    used = "scored Rio Grande outlook rows (issued monthly, test years, full 52-week future known)"
    error = lambda column: by_year(rg, lambda g: float((g[column] - g["y_weeks"]).abs().mean()))
    rows = by_year(rg, len)
    baselines = {"Same as now": "weeks_same_as_now", "Last year": "weeks_last_year", "Usual": "weeks_usual"}
    return [compare(f"12-month mean absolute error (weeks) minus {name}", error("weeks_model"), error(column), rows,
                    True, used, b_name=name) for name, column in baselines.items()]


def intervals_item(alert_rows, alert, rg_scored):
    """The content of intervals_v1.json."""
    onset_rows = alert_rows[alert_rows["cls"] < D2_CLASS]
    return {
        "what": "Year-block intervals around version 1's system-minus-rule differences. Lower is better for every "
                "quantity here (a cost, or an error in weeks), so a difference below zero favours the system.",
        "alert": alert_comparisons(alert_rows, "Rio Grande test rows of the 4-week alert (weekly, 2019 on)",
                                   alert["headline"]["cheapest_baseline_on_test"], "the cheapest baseline"),
        "onset": alert_comparisons(onset_rows, "Rio Grande test rows of the 4-week alert where the county is NOT at "
                                               "D2 or worse on the issue date. Persistence never fires on these rows, "
                                               "so its cost here is the cost of never warning.",
                                   alert["onset"]["best_rule"], "the best onset rule"),
        "season": season_comparisons(rg_scored),
        "year": year_comparisons(rg_scored),
    }


# ---------------------------------------------------------------------------------------------
# Item 2: the annual trigger
# ---------------------------------------------------------------------------------------------
def trigger_item(scored, history):
    """The content of trigger_annual.json: the annual table, and value differences with intervals.

    value = (drought seasons caught - cost ratio x firings) / decisions. Higher is better.
    """
    table = run_trigger_annual(scored, history=history)
    rows, frequency, _ = annual_rows(scored, history=history)
    year_of = rows["date"].dt.year.to_numpy()
    years = sorted(set(int(y) for y in year_of))
    y = (rows["y_season"] == 1).to_numpy()
    decisions = pd.Series({year: int((year_of == year).sum()) for year in years})
    used = "Rio Grande outlooks issued in March, one per county per year (scored rows)"

    def value_by_year(fires, ratio):
        fires = np.asarray(fires, dtype=bool)
        return pd.Series({year: float(((fires & y)[year_of == year].sum() - ratio * fires[year_of == year].sum())
                                      / (year_of == year).sum()) for year in years})

    differences = []
    for ratio in COST_RATIOS:
        fires = annual_fires(rows, frequency, ratio)
        forecast = value_by_year(fires["forecast"], ratio)
        for key, name, added in (("d1_rule", "D1 or worse now", False), ("d0_rule", "D0 or worse now", True),
                                 ("class_frequency", "Class-conditional frequency", True)):
            entry = compare(f"forecast value minus '{name}' value at cost ratio {ratio}", forecast,
                            value_by_year(fires[key], ratio), decisions, False, used, a_name="forecast", b_name=name)
            differences.append({"cost_ratio": ratio, "rule": name, "rule_is_added": added, **entry})
    return {"what": "The pre-season trigger with one decision per county per year. The value of a rule is "
                    "(drought seasons caught - cost ratio x firings) / decisions; higher is better, so a difference "
                    "above zero favours the forecast.",
            "history": "the full table of monthly issue rows (Rio Grande rows of it), so the class-frequency rule "
                       "has the years before the first test year",
            "table": table, "value_differences": differences}


# ---------------------------------------------------------------------------------------------
# Item 3: calibration
# ---------------------------------------------------------------------------------------------
def calibration_item(history, rg_scored):
    """The content of calibration.json.

    history   : every Rio Grande issue row, with "p_chain" = the 6-month forecast chained from
                SELECT_START (2005), as v2.py does, so the first test year has three past years
    rg_scored : the scored Rio Grande rows (the system's own p_season, and p_season_usual)
    """
    history = history.assign(p_calibrated=calibrate_by_past(history, "p_chain", "y_season", SEASON_WEEKS),
                             class_frequency=class_frequency_by_past(history, "y_season", SEASON_WEEKS))
    rows = rg_scored.merge(history[["fips", "date", "p_chain", "p_calibrated", "class_frequency"]], on=["fips", "date"],
                           how="left", validate="one_to_one")
    forecasts = {"raw": "p_season", "calibrated": "p_calibrated", "usual": "p_season_usual",
                 "class_frequency": "class_frequency"}
    complete = rows[list(forecasts.values())].notna().all(axis=1)
    used = rows[complete]
    score = {name: brier(used["y_season"], used[column]) for name, column in forecasts.items()}
    brier_by_year = lambda column: by_year(used, lambda g: brier(g["y_season"], g[column]))
    n = by_year(used, len)
    which = "scored Rio Grande outlook rows that have all four probabilities"
    cost = lambda column: cost_by_year(used, "y_season", lambda g: g[column] >= SEASON_THRESHOLD)
    return {
        "what": "The 6-month probability, raw (the system) and calibrated. The calibrated value is ADDED and is not "
                "the system: for each year an isotonic curve is fitted on forecasts whose answers were already "
                "known before that New Year, and that year's forecasts are passed through it.",
        "calibration_history": f"Rio Grande issue rows with the version 1 forest chained from {SELECT_START} "
                               "(same inputs, settings and seed), as v2.py does, so the first test year has past "
                               "forecasts to learn from",
        "rows_scored": int(len(rows)), "rows_with_all_four_probabilities": int(complete.sum()),
        "largest_gap_between_chained_and_system_forecast": float((rows["p_chain"] - rows["p_season"]).abs().max()),
        "coverage": calibration_coverage(history, "p_chain", "y_season", SEASON_WEEKS),
        "brier": score,
        "skill": {f"{name}_against_{reference}": 1 - score[name] / score[reference]
                  for name in ("raw", "calibrated") for reference in ("usual", "class_frequency")},
        "skill_means": "1 - Brier / reference Brier. Above zero means better than the reference.",
        "brier_differences": [
            compare("Brier of the raw forecast minus Brier of 'usual'", brier_by_year("p_season"),
                    brier_by_year("p_season_usual"), n, True, which, a_name="raw", b_name="usual"),
            compare("Brier of the raw forecast minus Brier of class frequency", brier_by_year("p_season"),
                    brier_by_year("class_frequency"), n, True, which, a_name="raw", b_name="class frequency"),
            compare("Brier of the calibrated forecast minus Brier of the raw forecast", brier_by_year("p_calibrated"),
                    brier_by_year("p_season"), n, True, which, a_name="calibrated", b_name="raw"),
        ],
        "reliability": {"raw": reliability(used["y_season"], used["p_season"]),
                        "calibrated": reliability(used["y_season"], used["p_calibrated"])},
        "cost_at_threshold": compare(f"6-month cost at threshold {SEASON_THRESHOLD}: calibrated minus raw",
                                     cost("p_calibrated"), cost("p_season"), None, True, which,
                                     a_name="calibrated", b_name="raw"),
    }


# ---------------------------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------------------------
def header(frozen):
    """What every round-3 file says about itself. frozen: the content of reports/frozen/v1/metrics.json."""
    return {"added": True, "declared_in": DECLARED_IN, "score_through": SCORE_THROUGH,
            "computed_against_manifest_sha256": frozen["frozen"]["manifest_sha256"],
            "computed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            **git_state(), "draws": DRAWS, "seed": SEED}


def write_items(items, folder=None, force=False):
    """Write {file name: content} into the round-3 folder. If ANY of the files exists and force
    is False, nothing is written and an error names them: an item is scored once."""
    folder = ROUND3 if folder is None else folder
    existing = [name for name in items if (folder / name).exists()]
    if existing and not force:
        raise RuntimeError(f"already scored, so nothing was written: {', '.join(existing)} in {folder}. "
                           "To replace them on purpose, run: PYTHONPATH=src python -m farmdrought.round3 --force")
    folder.mkdir(parents=True, exist_ok=True)
    for name, content in items.items():
        (folder / name).write_text(json.dumps(content, indent=2, default=lambda value: value.item()) + "\n")
    return [folder / name for name in items]


ITEMS = ["intervals_v1.json", "trigger_annual.json", "calibration.json", "allocation.json"]


def main(force=False):
    # Refuse early, before any scoring, if this would replace a result or does not match the freeze.
    existing = [name for name in ITEMS if (ROUND3 / name).exists()]
    if existing and not force:
        write_items({name: None for name in existing})   # raises with the names
    with open(FROZEN / "metrics.json") as f:
        frozen = json.load(f)
    problems = check_manifest()
    if problems or sha256_of(MANIFEST) != frozen["frozen"]["manifest_sha256"]:
        raise RuntimeError("the raw inputs or the manifest differ from the ones the frozen results were scored on, "
                           "so nothing was scored:\n  " + "\n  ".join(problems or ["data/manifest.json changed"]))

    # The same two calls evaluate() makes.
    panel, alert = run_alert(score_through=SCORE_THROUGH)
    scored, season, year = run_outlook(panel)
    ours = (alert["headline"]["system_cost"], season["focus"]["system_cost"], year["focus"]["mae_system"])
    theirs = (frozen["headline"]["system_cost"], frozen["season"]["focus"]["system_cost"],
              frozen["year"]["focus"]["mae_system"])
    if ours != theirs:
        raise RuntimeError(f"this run's headline numbers {ours} are not the frozen ones {theirs}, so nothing was written")

    _, _, test = split_masks(panel)
    alert_rows = panel[test & (panel["river"] == FOCUS_RIVER)]
    rg_scored = scored[scored["river"] == FOCUS_RIVER].reset_index(drop=True)
    issue_table = issue_rows(panel)
    # The calibration history: the version 1 forest chained from 2005 on Rio Grande rows, as in v2.py.
    history = issue_table[issue_table["river"] == FOCUS_RIVER].reset_index(drop=True)
    everyone = pd.Series(True, index=history.index)
    history["p_chain"] = chain(history, "y_season", SEASON_WEEKS, FEATURES_SEASON, make_classifier, everyone, everyone,
                               first_year=SELECT_START)

    top = header(frozen)
    items = {
        "intervals_v1.json": {**top, **intervals_item(alert_rows, alert, rg_scored)},
        "trigger_annual.json": {**top, **trigger_item(scored, issue_table)},
        "calibration.json": {**top, **calibration_item(history, rg_scored)},
        "allocation.json": {**top, "what": "The budget-ranking backtest (allocation.py). Higher share is better.",
                            **run_allocation(scored, draws=DRAWS, seed=SEED)},
    }
    for path in write_items(items, force=force):
        print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--force"]):
        sys.exit("usage: python -m farmdrought.round3 [--force]")
    main(force="--force" in sys.argv)
