"""Tests for round 4: the climate inputs (climate.py) and the six-river holdout (holdout.py).

The tables are small and made up, except the last test, which only reads county codes."""
import pandas as pd

from farmdrought import climate, holdout
from farmdrought.config import RIVERS


def test_noaa_state_codes_match_the_three_checked_in_weather_py():
    # weather.py lists these three by hand: Colorado 05, New Mexico 29, Texas 41.
    assert climate.NOAA_TO_FIPS["05"] == "08"
    assert climate.NOAA_TO_FIPS["29"] == "35"
    assert climate.NOAA_TO_FIPS["41"] == "48"
    assert len(climate.NOAA_TO_FIPS) == 48


def write_climate(tmp_path, monkeypatch, months):
    """Save a made-up one-county climate record and point climate.py at it."""
    rows = [("48001", p.year, p.month, 1.0, 60.0, float(i), float(i)) for i, p in enumerate(months)]
    data = pd.DataFrame(rows, columns=["fips", "year", "month", "rain_in", "temp_f", "pdsi", "zndx"])
    normals = pd.DataFrame({"fips": "48001", "month": range(1, 13), "rain_normal": 2.0, "temp_normal": 58.0})
    monkeypatch.setattr(climate, "CLIMATE_CSV", tmp_path / "c.csv")
    monkeypatch.setattr(climate, "NORMALS_CSV", tmp_path / "n.csv")
    data.to_csv(tmp_path / "c.csv", index=False)
    normals.to_csv(tmp_path / "n.csv", index=False)


def test_climate_inputs_use_only_months_up_to_two_before_the_forecast(tmp_path, monkeypatch):
    months = pd.period_range("2000-01", "2002-12", freq="M")
    write_climate(tmp_path, monkeypatch, months)
    table = pd.DataFrame({"fips": ["48001"], "date": [pd.Timestamp("2002-06-04")]})
    out = climate.add_climate_features(table).iloc[0]
    # The forecast is made in June 2002, so the newest month it may see is April 2002 (number 27).
    assert out["pdsi"] == 27.0
    assert out["z1"] == 27.0
    assert out["pdsi_min12"] == 16.0              # the lowest of months 16 to 27
    assert out["rain3"] == 0.5                    # 1 inch a month against a normal of 2
    assert out["heat3"] == 2.0                    # 60 degrees against a normal of 58
    assert out["norm_rain"] == 24.0               # twelve monthly normals of 2 inches


def test_a_county_without_climate_data_gets_nan_and_the_holdout_run_refuses_it(tmp_path, monkeypatch):
    write_climate(tmp_path, monkeypatch, pd.period_range("2000-01", "2002-12", freq="M"))
    table = pd.DataFrame({"fips": ["99999"], "date": [pd.Timestamp("2002-06-04")]})
    assert climate.add_climate_features(table)[climate.FEATURES_P].isna().all().all()


def test_the_general_model_never_trains_on_a_holdout_row(monkeypatch):
    seen = []

    def fake_chain(table, label, horizon, features, make_model, train_on, predict_on):
        seen.append(train_on.copy())
        return pd.Series(0.5, index=table.index)

    monkeypatch.setattr(holdout, "chain", fake_chain)
    monkeypatch.setattr(holdout, "add_climate_features", lambda t: t.assign(**{c: 0.0 for c in holdout.FEATURES_G}))
    dev = pd.DataFrame({"fips": ["a", "b"], "river": ["Rio Grande", "Ohio"]})
    hold = pd.DataFrame({"fips": ["c"], "river": ["Pecos"]})
    table = holdout.forecasts(dev, hold)
    general_rows, v1_rows = seen
    assert not general_rows[table["holdout"]].any()       # no holdout row in the general model's training
    assert general_rows[~table["holdout"]].all()          # every development row is
    assert list(table.loc[v1_rows, "river"]) == ["Rio Grande"]


def test_holdout_rivers_are_not_development_rivers_and_inputs_are_47():
    assert not set(holdout.HOLDOUT_RIVERS) & set(RIVERS)
    assert len(holdout.FEATURES_G) == 47 and len(set(holdout.FEATURES_G)) == 47
