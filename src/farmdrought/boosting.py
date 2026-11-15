"""boosting.py: would gradient boosting have done better than the forest on the 6-month outlook?

ADDED in round 3 (ARCHITECTURE.md section 3.6, the cheap version: no GRU). Declared in
reports/decision.md ("Gradient boosting comparison") BEFORE this file was written. The forest
stays the reported system whatever this shows.

WHAT IT DOES
  - Trains scikit-learn's HistGradientBoostingClassifier (default settings, random_state 0;
    nothing is tuned) with the SAME inputs and the SAME forward chaining as the forest: for each
    test year 2008 to 2025, only rows whose 26-week answer was known before 1 January of that
    year, Rio Grande counties only, weeks up to config.SCORE_THROUGH.
  - Warns at the same fixed threshold, 0.25.
  - Scores it on exactly the Rio Grande rows of the FROZEN outlook file, beside the frozen
    forest's own forecasts and the "D1 or worse now" rule, which are read from that file and
    not recomputed.
  - Reports cost (3 x missed + false alarms; lower is better): boosting minus forest and
    boosting minus "D1 now", each with a year-block interval. A win needs an interval that
    excludes zero.

Run it with:  PYTHONPATH=src python -m farmdrought.boosting
              (writes reports/frozen/round3/boosting.json once; --force to replace)
"""
import json
import sys
from importlib.metadata import version

import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

from farmdrought.config import FOCUS_RIVER, FROZEN, MANIFEST, OUTLOOK, ROOT, SCORE_THROUGH, SEASON_THRESHOLD, SEASON_WEEKS
from farmdrought.drought import build_panel
from farmdrought.manifest import check_manifest, sha256_of
from farmdrought.outlook import FEATURES_SEASON, chain, issue_rows
from farmdrought.round3 import ROUND3, compare, cost_by_year, header, write_items

OUTPUT = "boosting.json"
DECLARED_IN = ('reports/decision.md, section "Gradient boosting comparison: declared Nov 15, 2026, before any of its '
               'code was written or run"')
ROWS_USED = "the Rio Grande rows of the frozen outlook file (issued monthly, 2008 to 2025, full 52-week future known)"


def make_boosting(seed=0):
    """Gradient boosting with scikit-learn's default settings. Nothing is tuned."""
    return HistGradientBoostingClassifier(random_state=seed)


def boosting_forecasts(table):
    """The boosting forecast for every Rio Grande issue row, by the forest's forward chaining.

    table : Rio Grande issue rows (outlook.issue_rows), with the inputs and y_season.
    Returns a Series of probabilities (NaN outside the test years 2008 to 2025).
    """
    everyone = pd.Series(True, index=table.index)
    return chain(table, "y_season", SEASON_WEEKS, FEATURES_SEASON, make_boosting, everyone, everyone)


def boosting_item(scored, p_boost):
    """The content of boosting.json (without its header).

    scored  : the frozen outlook rows for the Rio Grande (y_season, p_season, alarm_season_d1, date)
    p_boost : the boosting probability for each of those rows, in the same order
    """
    scored = scored.assign(p_boost=list(p_boost))
    if scored["p_boost"].isna().any():
        raise ValueError(f"{int(scored['p_boost'].isna().sum())} scored rows have no boosting forecast")
    boosting = cost_by_year(scored, "y_season", lambda g: g["p_boost"] >= SEASON_THRESHOLD)
    forest = cost_by_year(scored, "y_season", lambda g: g["p_season"] >= SEASON_THRESHOLD)
    d1 = cost_by_year(scored, "y_season", "alarm_season_d1")
    return {
        "what": "Gradient boosting against the frozen forest and the 'D1 or worse now' rule on the 6-month outlook. "
                "Cost = 3 x missed + false alarms; lower is better, so a difference below zero favours boosting. "
                "The forest stays the reported system.",
        "model": {"class": "sklearn.ensemble.HistGradientBoostingClassifier", "settings": "defaults", "random_state": 0,
                  "scikit_learn": version("scikit-learn"), "inputs": FEATURES_SEASON, "trained_on": "Rio Grande rows only",
                  "threshold": SEASON_THRESHOLD, "threshold_note": "the fixed break-even threshold; not chosen on any data"},
        "rows": int(len(scored)), "years": int(scored["date"].dt.year.nunique()),
        "cost": {"boosting": float(boosting.sum()), "forest": float(forest.sum()), "D1 now": float(d1.sum())},
        "comparisons": [
            compare("6-month cost: boosting minus the frozen forest", boosting, forest, None, True, ROWS_USED,
                    a_name="boosting", b_name="forest"),
            compare("6-month cost: boosting minus 'D1 or worse now'", boosting, d1, None, True, ROWS_USED,
                    a_name="boosting", b_name="D1 now"),
        ],
    }


def main(force=False):
    if (ROUND3 / OUTPUT).exists() and not force:
        write_items({OUTPUT: None})   # raises: already scored
    with open(FROZEN / "metrics.json") as f:
        frozen = json.load(f)
    problems = check_manifest()
    if problems or sha256_of(MANIFEST) != frozen["frozen"]["manifest_sha256"]:
        raise RuntimeError("the raw inputs or the manifest differ from the ones the frozen results were scored on, "
                           "so nothing was scored:\n  " + "\n  ".join(problems or ["data/manifest.json changed"]))

    table = issue_rows(build_panel(score_through=SCORE_THROUGH))
    table = table[table["river"] == FOCUS_RIVER].reset_index(drop=True)
    table["p_boost"] = boosting_forecasts(table)

    # The frozen outlook file gives the rows to score, the forest's own forecasts and the rule.
    scored = pd.read_parquet(FROZEN / OUTLOOK.name)
    scored = scored[scored["river"] == FOCUS_RIVER].assign(date=lambda t: pd.to_datetime(t["date"]))
    scored = scored.merge(table[["fips", "date", "p_boost"]], on=["fips", "date"], how="left", validate="one_to_one")
    content = {**header(frozen), "declared_in": DECLARED_IN, **boosting_item(scored.drop(columns="p_boost"), scored["p_boost"])}
    for path in write_items({OUTPUT: content}, force=force):
        print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--force"]):
        sys.exit("usage: python -m farmdrought.boosting [--force]")
    main(force="--force" in sys.argv)
