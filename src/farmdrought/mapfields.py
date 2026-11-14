"""mapfields.py: extra per-county numbers for the app's risk map.

The map shows one dot per county along the river, like a fire-danger map. For each county
this file adds three things to this week's forecast:

  1. RISK    : one overall level (Low / Watch / Warning) to color the dot.
  2. LENGTH  : how long severe drought could last, as a range, plus how long past droughts
               in that county actually lasted.
  3. DAMAGES : what that drought could cost a rancher in bought feed.

IMPORTANT: nothing here is a new model. Every number is worked out from the three tested
forecasts and the county's own drought history. The damage figure rests on stated
assumptions and was NOT tested against real losses.
"""
import numpy as np
import pandas as pd

from farmdrought.config import FEED_COST_PER_HEAD_MONTH, WEEKS_PER_MONTH

# The new columns, in the order they are added to the end of latest.parquet
MAP_COLUMNS = ["risk_level", "weeks_low", "weeks_high", "typical_drought_weeks", "longest_drought_weeks",
               "damage_months", "damage_usd_per_100_head"]

LEVELS = ["Low", "Watch", "Warning"]  # from mildest to worst


def spell_history(panel):
    """How long did past severe droughts last in each county?

    A "spell" is an unbroken run of weeks at D2 or worse. Returns one row per county with:
      typical_drought_weeks : the median length of its finished spells (0 if it never had one)
      longest_drought_weeks : its longest spell on record, counting one still going on
    """
    panel = panel.sort_values(["fips", "date"])
    streak = panel["d2_streak"]
    # A spell ends on a week that is in D2 when the same county's next week is not.
    next_streak = panel.groupby("fips")["d2_streak"].shift(-1)
    spell_ends = panel[(streak > 0) & (next_streak == 0)]
    typical = spell_ends.groupby("fips")["d2_streak"].median()
    longest = panel.groupby("fips")["d2_streak"].max()
    return pd.DataFrame({"typical_drought_weeks": typical, "longest_drought_weeks": longest}).fillna(0)


def add_map_fields(now, panel, error_by_river):
    """Add the map columns to this week's rows.

    now            : this week's forecasts, one row per county
    panel          : the full county-week history
    error_by_river : the 12-month outlook's measured average error in weeks, per river
    """
    # 1. RISK: the worse of the 4-week level and the 6-month level
    worst = np.maximum(now["tier"].map(LEVELS.index), now["season_tier"].map(LEVELS.index))
    now["risk_level"] = [LEVELS[i] for i in worst]

    # 2. LENGTH: the 12-month estimate, plus and minus its measured average error on that
    #    river. It cannot go below 0 or above 52 weeks.
    error = now["river"].map(error_by_river)
    now["weeks_low"] = (now["weeks_model"] - error).clip(lower=0)
    now["weeks_high"] = (now["weeks_model"] + error).clip(upper=52)
    #    And what history says: how long this county's past droughts lasted.
    history = spell_history(panel)
    now["typical_drought_weeks"] = now["fips"].map(history["typical_drought_weeks"])
    now["longest_drought_weeks"] = now["fips"].map(history["longest_drought_weeks"])

    # 3. DAMAGES. Assumption: in a week of severe drought the pasture cannot feed the herd,
    #    so the rancher has to buy that week's feed. Then:
    #      months of bought feed = expected severe-drought weeks / weeks in a month
    #      cost per 100 cattle   = months x monthly feed cost per head x 100
    now["damage_months"] = now["weeks_model"] / WEEKS_PER_MONTH
    now["damage_usd_per_100_head"] = now["damage_months"] * FEED_COST_PER_HEAD_MONTH * 100
    return now


def range_coverage(scored, error):
    """Honesty check on the length range: in testing, how often did the truth fall inside
    "estimate plus or minus the average error"? Returns a share between 0 and 1."""
    inside = (scored["y_weeks"] - scored["weeks_model"]).abs() <= error
    return round(float(inside.mean()), 3)
