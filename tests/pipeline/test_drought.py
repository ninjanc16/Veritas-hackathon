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


# ---------------- 6-month and 12-month truths ----------------
from farmdrought.drought import label_season, label_weeks


def one_county(weeks_in_d2, n_weeks=40):
    """A single county that is in D2 (class 3) on the given weeks, and at 0 otherwise."""
    classes = np.zeros((1, n_weeks))
    classes[0, weeks_in_d2] = 3
    return classes


def test_season_label_needs_8_weeks_in_a_row_inside_the_window():
    # A 10-week window from week 0 covers weeks 1..10
    assert label_season(one_county(range(2, 10)), horizon=10, run=8)[0, 0] == 1   # weeks 2-9: 8 in a row
    assert label_season(one_county(range(2, 9)), horizon=10, run=8)[0, 0] == 0    # weeks 2-8: only 7
    # 8 D2 weeks in total, but with a gap, so the longest run is only 4
    assert label_season(one_county([1, 2, 3, 4, 6, 7, 8, 9]), horizon=10, run=8)[0, 0] == 0


def test_season_label_ignores_drought_weeks_before_the_window():
    # The county is in D2 for weeks 0..7 (8 weeks in a row). Standing at week 3, the
    # window is weeks 4..13, and only weeks 4-7 (4 weeks) are inside it. So the answer is 0.
    classes = one_county(range(0, 8))
    assert label_season(classes, horizon=10, run=8)[0, 3] == 0
    # Standing at week 0 the window is weeks 1..10: weeks 1-7 are inside, 7 in a row. Still 0.
    assert label_season(classes, horizon=10, run=8)[0, 0] == 0


def test_weeks_label_counts_d2_weeks_in_the_window_only():
    classes = one_county([0, 1, 2, 5, 6, 20])
    y = label_weeks(classes, horizon=10)
    assert y[0, 0] == 4      # window weeks 1..10 holds weeks 1, 2, 5, 6
    assert y[0, 2] == 2      # window weeks 3..12 holds weeks 5, 6
    assert y[0, 10] == 1     # window weeks 11..20 holds week 20
    assert np.isnan(y[0, 30:]).all()  # the last 10 weeks have no full future yet
