"""baselines.py: the simple rules our model has to beat (4-week alert).

A model is only worth having if it beats rules a person could apply with no model at all.
Each rule gives a True/False alarm for every row.

  alarm_persistence : "the future equals today". Warn if the county is in D2 or worse now.
  alarm_d1_now      : warn if the county is in D1 or worse now (one step earlier).
  alarm_worsening   : warn if in D2 now, or in D1 and worse than 4 weeks ago.
  alarm_calendar    : "typical for the time of year". Warn in the weeks of the year when
                      severe drought was common on that river in the past.
"""
from farmdrought.config import D2_CLASS, MISS_COST
from farmdrought.evaluate import pick_threshold

# column name -> the plain name used in tables
BASELINES = {
    "alarm_persistence": "Persistence",
    "alarm_d1_now": "D1 now",
    "alarm_worsening": "Worsening",
    "alarm_calendar": "Calendar",
}


def add_baselines(panel, train, val):
    """Add the four baseline alarm columns to the panel.

    train, val : True/False masks marking the training rows and the validation rows.
    Only the calendar rule needs them, because it learns from the past.
    """
    d1 = D2_CLASS - 1
    panel["alarm_persistence"] = panel["cls"] >= D2_CLASS
    panel["alarm_d1_now"] = panel["cls"] >= d1
    panel["alarm_worsening"] = (panel["cls"] >= D2_CLASS) | ((panel["cls"] >= d1) & (panel["chg4"] > 0))

    # Calendar rule, step 1: for each river and week of the year, how often did severe
    # drought follow? Learned from TRAINING rows only (leakage rule 3).
    panel["woy"] = panel["date"].dt.isocalendar().week.astype(int)
    usual = panel[train].groupby(["river", "woy"])["y"].mean().rename("usual_rate")
    rate = panel.join(usual, on=["river", "woy"])["usual_rate"].fillna(0)

    # Step 2: for each river, pick how high that rate must be to warn.
    # Picked on that river's VALIDATION rows, never on test rows.
    panel["alarm_calendar"] = False
    for river in panel["river"].unique():
        on_river = panel["river"] == river
        pick = val & on_river
        threshold = pick_threshold(rate[pick], panel.loc[pick, "y"], MISS_COST)
        panel.loc[on_river, "alarm_calendar"] = rate[on_river] >= threshold
    return panel
