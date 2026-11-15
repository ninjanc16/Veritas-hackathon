"""prospective.py: write down each week's forecasts BEFORE the truth is known.

ADDED in round 3 (ARCHITECTURE.md section 3.8). Every other test in this project looks back at
years whose answers already existed. This log looks forward: one file per issue week, written
when the forecast is made, so that months later it can be scored against what really happened
with no way to have peeked.

NOTHING IS SCORED YET. This file only records. Each entry says when its answer will be known.

Rules:
  - One file per issue week: reports/prospective/<issue date>.json.
  - Append-only. A week that is already logged is never rewritten, even if the forecast for it
    is recomputed later (for example after a data correction). The first record stands.
  - Each file's sha256 is added to reports/prospective.sha256 when it is written. CI fails if a
    listed file changes, or if a line of that list changes or disappears (manifest.py and
    tools/hash_list_gate.py).

Run it with:  PYTHONPATH=src python -m farmdrought.prospective
(The daily refresh runs it after rebuilding this week's forecast. On a day when the week is
already logged it says so and changes nothing.)
"""
import json
import sys
from datetime import datetime

import pandas as pd

from farmdrought.config import (ALERT_WEEKS, FROZEN, LATEST, REPORTS, ROOT, SEASON_THRESHOLD, SEASON_WEEKS, USDM_JSON,
                                YEAR_WEEKS, live_data, raw_path)
from farmdrought.manifest import add_new_prospective_files, sha256_of

PROSPECTIVE = REPORTS / "prospective"
HEADER = ("A forecast log, written before the truth was known. NOTHING HERE IS SCORED YET: each forecast can be scored "
          "only after the date in its 'answer_known_after' field. This file is never rewritten.")


def entry(latest, frozen, drought_file_sha256, logged_at=None):
    """The record for one issue week.

    latest : this week's forecasts (data/processed/latest.parquet): one row per county
    frozen : the frozen metrics (for the alarm threshold and what the model was scored on)
    """
    issue = pd.Timestamp(latest["date"].iloc[0])
    assert latest["date"].nunique() == 1, "the latest table must hold one week only"
    after = lambda weeks: str((issue + pd.Timedelta(weeks=weeks)).date())
    block = frozen["frozen"]
    return {
        "header": HEADER,
        "issue_date": str(issue.date()),
        "logged_at": logged_at or datetime.now().astimezone().isoformat(timespec="seconds"),
        "model_version": {
            "name": "version 1 (random forests; settings, inputs and thresholds as frozen)",
            "note": "The live forests are retrained each week on every Rio Grande row whose answer is known; "
                    "the settings, inputs and alarm thresholds do not change.",
            "frozen_results_code_commit": block["git_commit"], "frozen_score_through": block["score_through"],
        },
        "manifest_sha256": block["manifest_sha256"],
        "drought_file_sha256": drought_file_sha256,
        "forecasts": [
            {"horizon_weeks": ALERT_WEEKS, "column": "p_model", "kind": "probability",
             "question": "Will the county reach D2 or worse in any of the next 4 weeks?",
             "alarm_threshold": frozen["alert_threshold"], "answer_known_after": after(ALERT_WEEKS)},
            {"horizon_weeks": SEASON_WEEKS, "column": "p_season", "kind": "probability",
             "question": "Will the next 26 weeks hold 8 or more weeks in a row at D2 or worse?",
             "alarm_threshold": SEASON_THRESHOLD, "answer_known_after": after(SEASON_WEEKS)},
            {"horizon_weeks": YEAR_WEEKS, "column": "weeks_model", "kind": "number of weeks",
             "question": "How many of the next 52 weeks will be at D2 or worse?",
             "answer_known_after": after(YEAR_WEEKS)},
        ],
        "counties": [{"fips": row.fips, "county": row.county, "state": row.state, "river": row.river, "cls": int(row.cls),
                      "p_model": round(float(row.p_model), 4), "p_season": round(float(row.p_season), 4),
                      "weeks_model": round(float(row.weeks_model), 2)} for row in latest.itertuples()],
    }


def log_week(record, folder=None):
    """Write one issue week's record. Raises FileExistsError if that week is already logged:
    the log only grows, and a week's first record is never replaced. Returns the path."""
    folder = PROSPECTIVE if folder is None else folder
    path = folder / f"{record['issue_date']}.json"
    if path.exists():
        raise FileExistsError(f"{path.name} is already logged and is never rewritten")
    folder.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, indent=1) + "\n")
    return path


def main():
    with open(FROZEN / "metrics.json") as f:
        frozen = json.load(f)
    with live_data():   # the drought file this week's forecast was made from
        drought_hash = sha256_of(raw_path(USDM_JSON))
    record = entry(pd.read_parquet(LATEST), frozen, drought_hash)
    try:
        print("logged", log_week(record).relative_to(ROOT), "- not scored yet")
    except FileExistsError as already:
        print(already)
    # Record the new file's hash. Only files not yet listed get a line; a line is never changed.
    listed = add_new_prospective_files()
    if listed:
        print("listed in reports/prospective.sha256:", ", ".join(listed))


if __name__ == "__main__":
    sys.exit(main())
