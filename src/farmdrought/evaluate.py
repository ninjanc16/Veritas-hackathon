"""evaluate.py: score a set of alarms against what really happened.

Everything is scored with one cost rule:
    cost = MISS_COST x missed droughts + false alarms
A lower cost is better. Missing a drought counts 3 times as much as a false alarm.
"""
import numpy as np

from farmdrought.config import D2_CLASS, MISS_COST


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
