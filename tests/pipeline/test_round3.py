"""Tests for the round 3 evaluation work (ARCHITECTURE.md section 3).

Every table here is small and made up. Nothing in this file reads the real data."""
import json

import numpy as np
import pandas as pd
import pytest

from farmdrought.prob_calibration import brier, calibrate_by_past, class_frequency_by_past, reliability
from farmdrought.uncertainty import excludes_zero, resample_years, year_block_bootstrap

YEARS = list(range(2008, 2020))
# Twelve made-up yearly costs. A is sometimes lower and sometimes higher than B.
COST_A = pd.Series([31, 12, 47, 8, 26, 55, 19, 40, 3, 62, 28, 17], index=YEARS, dtype=float)
COST_B = pd.Series([35, 10, 52, 9, 20, 61, 25, 38, 7, 70, 22, 21], index=YEARS, dtype=float)


def test_bootstrap_is_seeded_and_resamples_years():
    # Arrange: the same inputs, run twice with seed 0 and once with seed 1

    # Act
    first = year_block_bootstrap(COST_A, COST_B, draws=2000, seed=0)
    again = year_block_bootstrap(COST_A, COST_B, draws=2000, seed=0)
    other = year_block_bootstrap(COST_A, COST_B, draws=2000, seed=1)

    # Assert: same seed, same answer; another seed, another interval; the unit is the year
    assert first == again
    assert (first["lo"], first["hi"]) != (other["lo"], other["hi"])
    assert first["diff"] == other["diff"] == COST_A.sum() - COST_B.sum()
    assert first["n_years"] == 12 and first["years_a_better"] == 8
    assert json.loads(json.dumps(first)) == first            # plain numbers only


def test_one_extreme_year_is_included_or_left_out_as_a_whole():
    # Arrange: four years tie exactly except 2003, where A is 1,000 lower. A resample then
    # favours A only if 2003 was drawn at least once: 1 - (3/4)^4 = 0.684 of resamples when
    # whole years are drawn. Every resampled difference is -1000 x (times 2003 was drawn).
    a = {2001: 5.0, 2002: 5.0, 2003: 0.0, 2004: 5.0}
    b = {2001: 5.0, 2002: 5.0, 2003: 1000.0, 2004: 5.0}

    # Act
    result = year_block_bootstrap(a, b, draws=10000, seed=0)

    # Assert
    assert result["n_years"] == 4 and result["years_a_better"] == 1
    assert result["diff"] == -1000.0
    assert result["share_draws_a_better"] == pytest.approx(1 - 0.75 ** 4, abs=0.02)
    assert result["hi"] == 0.0                               # 2003 left out entirely
    assert result["lo"] % 1000 == 0 and result["lo"] <= -2000


def test_every_resample_holds_as_many_years_as_the_original():
    # Arrange
    rng = np.random.default_rng(0)

    # Act
    picked = resample_years(7, 500, rng, block=1)

    # Assert: 7 positions per resample, all of them real years, and drawn with replacement
    assert picked.shape == (500, 7)
    assert picked.min() == 0 and picked.max() == 6
    assert any(len(set(row)) < 7 for row in picked)


def test_identical_policies_give_a_zero_interval_that_is_not_a_win():
    # Arrange / Act
    result = year_block_bootstrap(COST_A, COST_A.copy(), draws=1000, seed=0)

    # Assert
    assert (result["diff"], result["lo"], result["hi"]) == (0.0, 0.0, 0.0)
    assert result["share_draws_a_better"] == 0.0 and result["years_a_better"] == 0
    assert excludes_zero(result) is False


def test_a_policy_that_is_lower_every_year_has_an_interval_below_zero():
    # Arrange: A is exactly 2 lower than B in each of the 12 years
    lower = COST_B - 2

    # Act
    result = year_block_bootstrap(lower, COST_B, draws=1000, seed=0)

    # Assert
    assert result["lo"] < 0 and result["hi"] < 0
    assert result["share_draws_a_better"] == 1.0 and result["years_a_better"] == 12
    assert excludes_zero(result) is True
    # and the mirror image, B against A, is a clear loss, which also excludes zero
    assert excludes_zero(year_block_bootstrap(COST_B, lower, draws=1000, seed=0)) is True


def test_an_interval_that_touches_or_straddles_zero_is_not_a_win():
    assert excludes_zero({"lo": -1.0, "hi": 2.0}) is False
    assert excludes_zero({"lo": 0.0, "hi": 2.0}) is False
    assert excludes_zero({"lo": -2.0, "hi": 0.0}) is False
    assert excludes_zero({"lo": 0.5, "hi": 2.0}) is True


def test_weighted_mode_gives_the_hand_computed_weighted_mean():
    # Arrange: mean error per year, and how many rows each year has
    a = pd.Series({2001: 10.0, 2002: 20.0, 2003: 30.0})
    b = pd.Series({2001: 12.0, 2002: 18.0, 2003: 33.0})
    rows = pd.Series({2001: 1, 2002: 1, 2003: 2})
    # By hand: A = (10 + 20 + 2 x 30) / 4 = 22.5 and B = (12 + 18 + 2 x 33) / 4 = 24.0

    # Act
    weighted = year_block_bootstrap(a, b, weights=rows, draws=500, seed=0)
    totals = year_block_bootstrap(a, b, draws=500, seed=0)

    # Assert: -1.5 with weights (a plain mean would give -1.0), and -3.0 as a sum
    assert weighted["diff"] == pytest.approx(22.5 - 24.0)
    assert totals["diff"] == pytest.approx(60.0 - 63.0)
    # a weighted mean of yearly differences can never leave the range of those differences
    assert -3.0 <= weighted["lo"] <= weighted["hi"] <= 2.0


def test_block_of_two_keeps_adjacent_years_together():
    # Arrange: inside each pair (2001+2002, 2003+2004) A's lead in one year is cancelled by
    # the next. If pairs stay together every resample sums to exactly zero.
    a = {2001: 1.0, 2002: 0.0, 2003: 1.0, 2004: 0.0}
    b = {2001: 0.0, 2002: 1.0, 2003: 0.0, 2004: 1.0}

    # Act
    paired = year_block_bootstrap(a, b, draws=2000, seed=0, block=2)
    single = year_block_bootstrap(a, b, draws=2000, seed=0, block=1)

    # Assert
    assert (paired["lo"], paired["hi"]) == (0.0, 0.0) and paired["block"] == 2
    assert single["lo"] < 0 < single["hi"]                    # single years do not cancel


def test_block_of_two_with_an_odd_count_still_draws_the_original_number_of_years():
    # Arrange
    rng = np.random.default_rng(0)

    # Act: five years make the blocks (0, 1), (2, 3) and (4) alone
    picked = resample_years(5, 300, rng, block=2)

    # Assert: always five years, and a pair is never entered in the middle
    assert picked.shape == (300, 5)
    for row in picked:
        for position, year in enumerate(row):
            if year in (1, 3):                                # the second year of a pair
                assert position > 0 and row[position - 1] == year - 1


def test_mismatched_years_raise_an_error_that_names_them():
    # Arrange
    a = {2001: 1.0, 2002: 2.0}
    b = {2001: 1.0, 2003: 2.0}

    # Act / Assert
    with pytest.raises(ValueError, match="2002") as error:
        year_block_bootstrap(a, b)
    assert "2003" in str(error.value)
    with pytest.raises(ValueError, match="weights"):
        year_block_bootstrap(a, a, weights={2001: 5})


# ---------------------------------------------------------------------------------------------
# prob_calibration.py (section 3.3)
# ---------------------------------------------------------------------------------------------
def forecast_table():
    """Made-up monthly forecasts for 6 counties, 2001 to 2008 (576 rows). No random numbers:
    the forecast rises with a made-up dryness cycle, and the answer is yes when dryness is high."""
    rows = []
    for year in range(2001, 2009):
        for month in range(1, 13):
            for county in range(6):
                dryness = (7 * year + 5 * month + 11 * county) % 20          # 0..19
                rows.append({"date": pd.Timestamp(year=year, month=month, day=3), "fips": f"990{county:02d}",
                             "cls": dryness // 4, "p": 0.02 + dryness * 0.045,
                             "y": float(dryness + (year + month) % 5 >= 14)})
    return pd.DataFrame(rows)


def flip_answers(table, year):
    """A copy of the table in which every answer of one calendar year is turned round."""
    changed = table.copy()
    rows = changed["date"].dt.year == year
    changed.loc[rows, "y"] = 1 - changed.loc[rows, "y"]
    return changed


def test_calibration_ignores_the_year_it_scores():
    # Arrange
    table = forecast_table()
    in_2006 = table["date"].dt.year == 2006

    # Act
    original = calibrate_by_past(table, "p", "y", horizon=26)
    own_year_rewritten = calibrate_by_past(flip_answers(table, 2006), "p", "y", horizon=26)
    later_year_rewritten = calibrate_by_past(flip_answers(table, 2007), "p", "y", horizon=26)
    earlier_year_rewritten = calibrate_by_past(flip_answers(table, 2003), "p", "y", horizon=26)

    # Assert: 2006 does not move when 2006 or 2007 answers change, and does when 2003's change
    assert original[in_2006].equals(own_year_rewritten[in_2006])
    assert original[in_2006].equals(later_year_rewritten[in_2006])
    assert not original[in_2006].equals(earlier_year_rewritten[in_2006])
    assert not original[in_2006].equals(table.loc[in_2006, "p"])     # and it was really adjusted


def test_calibration_does_not_use_answers_whose_window_was_still_open_at_new_year():
    # Arrange: a forecast issued in September 2005 has a 26-week window that ends in 2006
    table = forecast_table()
    late_2005 = (table["date"].dt.year == 2005) & (table["date"].dt.month >= 8)
    changed = table.copy()
    changed.loc[late_2005, "y"] = 1 - changed.loc[late_2005, "y"]
    in_2006 = table["date"].dt.year == 2006

    # Act
    original = calibrate_by_past(table, "p", "y", horizon=26)
    rewritten = calibrate_by_past(changed, "p", "y", horizon=26)

    # Assert
    assert original[in_2006].equals(rewritten[in_2006])


def test_calibration_keeps_the_order_of_forecasts_within_a_year():
    # Arrange
    table = forecast_table()

    # Act
    calibrated = calibrate_by_past(table, "p", "y", horizon=26)

    # Assert: sorted by the raw forecast, the calibrated values never go down; all within 0..1
    for _, rows in table.groupby(table["date"].dt.year):
        in_raw_order = calibrated[rows.sort_values("p").index].to_numpy()
        assert (np.diff(in_raw_order) >= 0).all()
    assert calibrated.between(0, 1).all()


def test_calibration_leaves_early_years_and_missing_forecasts_alone():
    # Arrange: one forecast in 2007 is missing
    table = forecast_table()
    hole = table.index[table["date"].dt.year == 2007][0]
    table.loc[hole, "p"] = np.nan
    early = table["date"].dt.year <= 2003       # at New Year 2003 only 2001 and part of 2002 are known

    # Act
    calibrated = calibrate_by_past(table, "p", "y", horizon=26, min_years=3)

    # Assert
    assert calibrated[early].equals(table.loc[early, "p"])
    assert np.isnan(calibrated[hole]) and calibrated.drop(hole).notna().all()
    in_2004 = table["date"].dt.year == 2004     # 2001, 2002 and half of 2003: three past years
    assert not calibrated[in_2004].equals(table.loc[in_2004, "p"])


def test_class_frequency_matches_a_hand_computed_example():
    # Arrange: four forecasts in 2001 with known answers, then three in 2002
    table = pd.DataFrame({
        "date": pd.to_datetime(["2001-01-02", "2001-02-06", "2001-03-06", "2001-04-03",
                                "2002-03-05", "2002-03-05", "2002-03-05"]),
        "cls": [0, 3, 3, 0, 3, 0, 5],
        "y": [0.0, 1.0, 0.0, 0.0, 1.0, 1.0, 1.0]})

    # Act
    frequency = class_frequency_by_past(table, "y", horizon=26)

    # Assert: 2001 has no past. In 2002: class 3 was yes 1 time in 2, class 0 was yes 0 times
    # in 2, and class 5 was never seen so it gets the overall past rate, 1 in 4.
    assert frequency[:4].isna().all()
    assert frequency[4:].tolist() == [0.5, 0.0, 0.25]


def test_class_frequency_uses_only_past_years():
    # Arrange
    table = forecast_table()
    in_2006 = table["date"].dt.year == 2006

    # Act
    original = class_frequency_by_past(table, "y", horizon=26)
    own_year_rewritten = class_frequency_by_past(flip_answers(table, 2006), "y", horizon=26)
    later_year_rewritten = class_frequency_by_past(flip_answers(table, 2007), "y", horizon=26)
    earlier_year_rewritten = class_frequency_by_past(flip_answers(table, 2003), "y", horizon=26)

    # Assert
    assert original[in_2006].equals(own_year_rewritten[in_2006])
    assert original[in_2006].equals(later_year_rewritten[in_2006])
    assert not original[in_2006].equals(earlier_year_rewritten[in_2006])


def test_reliability_bins_hold_every_row_and_show_a_calibrated_forecast_as_calibrated():
    # Arrange: four forecasts of 25% with one yes, four of 75% with three yeses, and one of 100%
    p = [0.25] * 4 + [0.75] * 4 + [1.0]
    y = [1, 0, 0, 0] + [1, 1, 1, 0] + [1]

    # Act
    table = reliability(y, p, bins=10)

    # Assert
    assert len(table) == 10 and sum(row["n"] for row in table) == 9
    assert [row["bin_low"] for row in table] == [i / 10 for i in range(10)]
    filled = {row["bin_low"]: row for row in table if row["n"]}
    assert sorted(filled) == [0.2, 0.7, 0.9]
    assert all(row["observed"] == row["mean_p"] for row in filled.values())
    assert filled[0.9]["n"] == 1                               # 100% sits in the last slice
    empty = table[0]
    assert (empty["n"], empty["mean_p"], empty["observed"]) == (0, None, None)
    assert json.loads(json.dumps(table)) == table


def test_brier_is_zero_for_a_perfect_forecast_and_a_quarter_for_always_half():
    # Arrange
    y = [1, 0, 0, 1, 1]

    # Act / Assert
    assert brier(y, [1.0, 0.0, 0.0, 1.0, 1.0]) == 0.0
    assert brier(y, [0.5] * 5) == 0.25
    assert brier(y, [0.0, 1.0, 1.0, 0.0, 0.0]) == 1.0          # as wrong as it can be
