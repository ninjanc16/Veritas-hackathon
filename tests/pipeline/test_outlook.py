"""Checks that forward chaining never trains on a row whose answer overlaps the test year."""
import pandas as pd

from farmdrought.config import OUTLOOK_TEST, SEASON_WEEKS, YEAR_WEEKS
from farmdrought.outlook import folds, issue_rows


def test_training_answers_end_before_the_test_year(panel):
    table = issue_rows(panel)
    for label, horizon in [("y_season", SEASON_WEEKS), ("y_weeks", YEAR_WEEKS)]:
        years = []
        for year, train, test in folds(table, label, horizon):
            years.append(year)
            window_end = table.loc[train, "date"] + pd.Timedelta(weeks=horizon)
            assert window_end.max() < pd.Timestamp(f"{year}-01-01")   # answers known before the year
            assert (table.loc[test, "date"].dt.year == year).all()    # test rows are that year only
            assert not (train & test).any()
        assert years == list(range(OUTLOOK_TEST[0], OUTLOOK_TEST[1] + 1))


def test_issue_dates_are_the_first_week_of_each_month(panel):
    table = issue_rows(panel)
    # One issue date per month, and it is the earliest Drought Monitor date in that month
    per_month = table.groupby(table["date"].dt.to_period("M"))["date"].nunique()
    assert (per_month == 1).all()
    assert (table["date"].dt.day <= 7).all()
