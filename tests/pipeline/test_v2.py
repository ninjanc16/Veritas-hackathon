"""Tests for version 2: the choice of candidate must never see the year it is scored on."""
import numpy as np
import pandas as pd

from farmdrought.v2 import pick_by_past
from farmdrought.weather import PUBLISH_LAG_MONTHS, add_weather_features, monthly_features


def toy_table():
    """One county, one row per month from 2005 to 2025. The truth is always 10."""
    dates = pd.date_range("2005-01-01", "2025-12-01", freq="MS")
    table = pd.DataFrame({"date": dates, "y": 10.0})
    # candidate "a" is perfect up to 2010 and bad after. Candidate "b" is the opposite.
    early = table["date"].dt.year <= 2010
    candidates = pd.DataFrame({"a": np.where(early, 10.0, 0.0), "b": np.where(early, 0.0, 10.0)})
    return table, candidates


def test_choice_uses_only_past_years():
    table, candidates = toy_table()
    loss = lambda y, p: float((p - y).abs().mean())
    _, chosen = pick_by_past(table, candidates, "y", 4, loss)
    # In 2011 candidate "a" turns bad, but its record up to then is perfect, so the
    # chooser must still pick "a" for 2011. It may only switch once the bad years are known.
    assert chosen[2011] == "a"
    assert chosen[2025] == "b"


def test_changing_a_year_does_not_change_its_own_choice():
    table, candidates = toy_table()
    loss = lambda y, p: float((p - y).abs().mean())
    _, before = pick_by_past(table, candidates, "y", 4, loss)
    # rewrite the truth for 2012 and every later year
    table.loc[table["date"].dt.year >= 2012, "y"] = -999.0
    _, after = pick_by_past(table, candidates, "y", 4, loss)
    assert before[2012] == after[2012]


def test_weather_respects_the_publication_lag():
    # A forecast dated in March must carry January's weather numbers, not February's or March's.
    feats = monthly_features()
    fips = feats["fips"].iloc[0]
    row = add_weather_features(pd.DataFrame({"fips": [fips], "date": [pd.Timestamp("2020-03-03")]})).iloc[0]
    january = feats[(feats["fips"] == fips) & (feats["period"] == pd.Period("2020-01", "M"))].iloc[0]
    assert PUBLISH_LAG_MONTHS == 2
    assert row["rain3"] == january["rain3"] and row["heat12"] == january["heat12"]
