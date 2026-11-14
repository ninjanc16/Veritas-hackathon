"""Checks the truth labels on a tiny hand-made example, where the right answer is obvious."""
import numpy as np

from farmdrought.drought import d2_streak, label_alert

# 3 counties x 10 weeks. Class 3 is D2 (severe drought).
CLASSES = np.array([
    [0, 0, 0, 0, 0, 3, 3, 0, 0, 0],  # county A: two D2 weeks in the middle (weeks 5 and 6)
    [3, 3, 3, 3, 3, 3, 3, 3, 3, 3],  # county B: always in D2
    [0, 1, 2, 2, 1, 0, 0, 0, 0, 0],  # county C: never reaches D2
])


def test_alert_label_looks_at_the_next_4_weeks_only():
    y = label_alert(CLASSES, horizon=4)
    # County A: weeks 1 to 5 have a D2 week somewhere in their next 4 weeks.
    # Week 0 looks at weeks 1-4 (no D2). Week 6 looks at weeks 7-9 and beyond (no D2),
    # and its own D2 does NOT count, because the window starts at the next week.
    assert y[0, :6].tolist() == [0, 1, 1, 1, 1, 1]
    # County B is always 1 and county C is always 0, wherever the future is known
    assert y[1, :6].tolist() == [1] * 6
    assert y[2, :6].tolist() == [0] * 6


def test_alert_label_is_unknown_for_the_last_4_weeks():
    y = label_alert(CLASSES, horizon=4)
    assert np.isnan(y[:, 6:]).all()      # their 4-week future has not happened yet
    assert not np.isnan(y[:, :6]).any()


def test_d2_streak_counts_weeks_in_a_row():
    streak = d2_streak(CLASSES)
    assert streak[0].tolist() == [0, 0, 0, 0, 0, 1, 2, 0, 0, 0]
    assert streak[1].tolist() == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert streak[2].tolist() == [0] * 10
