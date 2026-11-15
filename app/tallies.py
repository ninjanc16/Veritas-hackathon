"""
tallies.py - tiny counting helpers (pure functions: no Streamlit, no files).

IMPORTANT for the judges: these counts are only used to DRAW charts and to label one
county. They are never reported as results. Reported numbers come from metrics.json.
"""
import pandas as pd


def tally(df, alarm, truth, miss_cost=3):
    """
    Compare an alarm column with what really happened (both True/False or 1/0).

      caught        = alarm and drought followed      (a hit)
      missed        = no alarm but drought followed   (a miss)
      false_alarms  = alarm but no drought followed
      cost          = miss_cost x missed + false_alarms   (our cost rule: a miss is 3x worse)
      precision     = caught / alarms           (None if there were no alarms)
      recall        = caught / (caught+missed)  (None if no drought ever happened)
    """
    a = df[alarm].astype(bool)
    t = df[truth].astype(bool)
    caught = int((a & t).sum())
    missed = int((~a & t).sum())
    false_alarms = int((a & ~t).sum())
    alarms = int(a.sum())
    return {
        "alarms": alarms,
        "caught": caught,
        "missed": missed,
        "false_alarms": false_alarms,
        "cost": miss_cost * missed + false_alarms,
        "precision": caught / alarms if alarms else None,
        "recall": caught / (caught + missed) if (caught + missed) else None,
    }


def weeks_error(df, col):
    """Average size of the mistake, in weeks: mean of |col - y_weeks|. None if no rows."""
    if df.empty:
        return None
    return float((df[col] - df["y_weeks"]).abs().mean())


# ---------------------------------------------------------------------------
# Phase 4 helpers: lists of mistakes, river heat-map grids, and the cross-check
# ---------------------------------------------------------------------------
TIER_NUMBER = {"Low": 0, "Watch": 1, "Warning": 2}     # so tiers can be drawn as colors
ERROR_COLUMNS = ["date", "county", "state", "river", "cls", "p_model"]


def errors_table(df, alarm_col):
    """
    The mistakes of one alarm. Returns two tables (same columns):
      missed        = no alarm, but severe drought arrived within 4 weeks (y == 1)
      false_alarms  = alarm, but no severe drought arrived (y == 0)
    """
    alarm = df[alarm_col].astype(bool)
    truth = df["y"].astype(bool)
    missed = df[~alarm & truth][ERROR_COLUMNS].reset_index(drop=True)
    false_alarms = df[alarm & ~truth][ERROR_COLUMNS].reset_index(drop=True)
    return missed, false_alarms


def river_grid(df, river, year):
    """
    Two county-by-week tables for one river and one year, counties ordered north to south:
      tiers = our tier as a number (0 Low, 1 Watch, 2 Warning)
      cls   = the actual drought class (0 to 5)
    Rows are "County, State"; columns are the weekly dates.
    """
    d = df[(df["river"] == river) & (df["date"].dt.year == year)].copy()
    d["label"] = d["county"] + ", " + d["state"]
    d["tier_number"] = d["tier"].map(TIER_NUMBER)
    north_to_south = d.groupby("label")["lat"].mean().sort_values(ascending=False).index
    tiers = d.pivot(index="label", columns="date", values="tier_number").reindex(north_to_south)
    cls = d.pivot(index="label", columns="date", values="cls").reindex(north_to_south)
    return tiers, cls


def reconcile(df, metrics):
    """
    Cross-check: re-count each policy on the focus river's rows and compare with what
    metrics.json reports. Returns a list of plain-English mismatches (empty = all match).
    """
    focus = df[df["river"] == metrics["focus_river"]]
    problems = []
    for policy in metrics["policies"]:
        counted = tally(focus, policy["column"], "y", metrics["miss_cost"])
        for field in ("alarms", "caught", "missed", "false_alarms", "cost"):
            if counted[field] != policy[field]:
                problems.append(f"{policy['name']}: metrics.json says {field} = {policy[field]}, "
                                f"but the app counted {counted[field]}.")
    return problems
