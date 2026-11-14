"""Checks the extra per-county columns made for the app's risk map."""
import pandas as pd

from farmdrought.config import FEED_COST_PER_HEAD_MONTH, LATEST
from farmdrought.mapfields import LEVELS, spell_history


def test_spell_history_on_a_hand_made_county():
    # d2_streak counts weeks in a row in severe drought. This county had spells of 2, 4 and 3 weeks.
    streak = [0, 1, 2, 0, 1, 2, 3, 4, 0, 0, 1, 2, 3, 0]
    panel = pd.DataFrame({"fips": "00001", "date": pd.date_range("2020-01-07", periods=len(streak), freq="7D"),
                          "d2_streak": streak})
    history = spell_history(panel)
    assert history.loc["00001", "typical_drought_weeks"] == 3   # the median of 2, 4 and 3
    assert history.loc["00001", "longest_drought_weeks"] == 4


def test_a_county_never_in_drought_gets_zero():
    panel = pd.DataFrame({"fips": "00002", "date": pd.date_range("2020-01-07", periods=5, freq="7D"),
                          "d2_streak": [0, 0, 0, 0, 0]})
    history = spell_history(panel)
    assert history.loc["00002", "typical_drought_weeks"] == 0
    assert history.loc["00002", "longest_drought_weeks"] == 0


def test_map_columns_in_the_latest_file_are_consistent():
    latest = pd.read_parquet(LATEST)
    # The overall level is never milder than either of the two levels it combines
    rank = lambda column: latest[column].map(LEVELS.index)
    assert (rank("risk_level") >= rank("tier")).all() and (rank("risk_level") >= rank("season_tier")).all()
    # The estimate sits inside its own range, and the range stays between 0 and 52 weeks
    assert (latest["weeks_low"] <= latest["weeks_model"]).all() and (latest["weeks_model"] <= latest["weeks_high"]).all()
    assert (latest["weeks_low"] >= 0).all() and (latest["weeks_high"] <= 52).all()
    assert (latest["typical_drought_weeks"] <= latest["longest_drought_weeks"]).all()
    # Dollars follow from months: months x feed cost per head x 100 head
    expected = latest["damage_months"] * FEED_COST_PER_HEAD_MONTH * 100
    assert (latest["damage_usd_per_100_head"] - expected).abs().max() < 1e-6
