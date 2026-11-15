"""Tests for the round 3 evaluation work (ARCHITECTURE.md section 3).

Every table here is small and made up. Nothing in this file reads the real data."""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from farmdrought.allocation import model_minus_rule, run_allocation
from farmdrought.config import COUNTY_RESERVOIR
from farmdrought.prob_calibration import brier, calibrate_by_past, class_frequency_by_past, reliability
from farmdrought.trigger import run_trigger, run_trigger_annual
from farmdrought.uncertainty import direction, excludes_zero, resample_years, year_block_bootstrap

YEARS = list(range(2008, 2020))
# Twelve made-up yearly costs. A is sometimes lower and sometimes higher than B.
COST_A = pd.Series([31, 12, 47, 8, 26, 55, 19, 40, 3, 62, 28, 17], index=YEARS, dtype=float)
COST_B = pd.Series([35, 10, 52, 9, 20, 61, 25, 38, 7, 70, 22, 21], index=YEARS, dtype=float)


def test_bootstrap_is_seeded_and_resamples_years():
    # Arrange: the same inputs, run twice with seed 0 and once with seed 1

    # Act
    first = year_block_bootstrap(COST_A, COST_B, draws=2000, seed=0, lower_is_better=True)
    again = year_block_bootstrap(COST_A, COST_B, draws=2000, seed=0, lower_is_better=True)
    other = year_block_bootstrap(COST_A, COST_B, draws=2000, seed=1, lower_is_better=True)

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
    result = year_block_bootstrap(a, b, draws=10000, seed=0, lower_is_better=True)

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
    result = year_block_bootstrap(COST_A, COST_A.copy(), draws=1000, seed=0, lower_is_better=True)

    # Assert
    assert (result["diff"], result["lo"], result["hi"]) == (0.0, 0.0, 0.0)
    assert result["share_draws_a_better"] == 0.0 and result["years_a_better"] == 0
    assert excludes_zero(result) is False


def test_a_policy_that_is_lower_every_year_has_an_interval_below_zero():
    # Arrange: A is exactly 2 lower than B in each of the 12 years
    lower = COST_B - 2

    # Act
    result = year_block_bootstrap(lower, COST_B, draws=1000, seed=0, lower_is_better=True)

    # Assert
    assert result["lo"] < 0 and result["hi"] < 0
    assert result["share_draws_a_better"] == 1.0 and result["years_a_better"] == 12
    assert excludes_zero(result) is True
    # and the mirror image, B against A, is a clear loss, which also excludes zero
    assert excludes_zero(year_block_bootstrap(COST_B, lower, draws=1000, seed=0, lower_is_better=True)) is True


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
    weighted = year_block_bootstrap(a, b, weights=rows, draws=500, seed=0, lower_is_better=True)
    totals = year_block_bootstrap(a, b, draws=500, seed=0, lower_is_better=True)

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
    paired = year_block_bootstrap(a, b, draws=2000, seed=0, block=2, lower_is_better=True)
    single = year_block_bootstrap(a, b, draws=2000, seed=0, block=1, lower_is_better=True)

    # Assert
    assert (paired["lo"], paired["hi"]) == (0.0, 0.0) and paired["block"] == 2
    assert single["lo"] < 0 < single["hi"]                    # single years do not cancel


def test_block_of_two_draws_whole_pairs_and_refuses_an_odd_number_of_years():
    # Arrange
    rng = np.random.default_rng(0)

    # Act: six years make the pairs (0, 1), (2, 3) and (4, 5)
    picked = resample_years(6, 300, rng, block=2)

    # Assert: always six years, made of whole pairs in order; five years are refused, because
    # cutting the last pair would keep first years more often than second years
    assert picked.shape == (300, 6)
    assert (picked[:, 0::2] % 2 == 0).all() and (picked[:, 1::2] == picked[:, 0::2] + 1).all()
    assert len({tuple(row) for row in picked}) > 1
    with pytest.raises(ValueError, match="even"):
        resample_years(5, 300, rng, block=2)
    with pytest.raises(ValueError, match="even"):
        year_block_bootstrap(COST_A[:5], COST_B[:5], block=2, lower_is_better=True)


def test_a_single_year_or_a_single_pair_is_refused_not_reported_as_certain():
    # Arrange: one year has nothing to resample, and two years are one pair under block=2
    one_a, one_b = {2010: 5.0}, {2010: 9.0}
    two_a, two_b = {2010: 5.0, 2011: 4.0}, {2010: 9.0, 2011: 8.0}

    # Act / Assert
    with pytest.raises(ValueError, match="at least two"):
        year_block_bootstrap(one_a, one_b, lower_is_better=True)
    with pytest.raises(ValueError, match="at least two"):
        year_block_bootstrap(two_a, two_b, block=2, lower_is_better=True)
    assert year_block_bootstrap(two_a, two_b, draws=50, lower_is_better=True)["n_years"] == 2


def test_missing_or_infinite_values_are_refused():
    # Arrange
    a_with_hole = COST_A.copy()
    a_with_hole[2011] = np.nan
    b_with_infinity = COST_B.copy()
    b_with_infinity[2015] = np.inf
    rows = pd.Series(10.0, index=YEARS)
    rows_with_hole = rows.copy()
    rows_with_hole[2019] = np.nan

    # Act / Assert: the message names the input and the year
    with pytest.raises(ValueError, match="per_year_a.*2011"):
        year_block_bootstrap(a_with_hole, COST_B, lower_is_better=True)
    with pytest.raises(ValueError, match="per_year_b.*2015"):
        year_block_bootstrap(COST_A, b_with_infinity, lower_is_better=True)
    with pytest.raises(ValueError, match="weights.*2019"):
        year_block_bootstrap(COST_A, COST_B, weights=rows_with_hole, lower_is_better=True)


def test_the_direction_must_be_stated_and_decides_what_better_means():
    # Arrange: A is lower than B in 8 of the 12 years
    # Act
    as_cost = year_block_bootstrap(COST_A, COST_B, draws=500, seed=0, lower_is_better=True)
    as_share = year_block_bootstrap(COST_A, COST_B, draws=500, seed=0, lower_is_better=False)

    # Assert: the interval is the same either way; only the "better" counts turn round
    with pytest.raises(TypeError):
        year_block_bootstrap(COST_A, COST_B)
    assert (as_cost["diff"], as_cost["lo"], as_cost["hi"]) == (as_share["diff"], as_share["lo"], as_share["hi"])
    assert as_cost["years_a_better"] == 8 and as_share["years_a_better"] == 4
    assert as_cost["share_draws_a_better"] + as_share["share_draws_a_better"] == pytest.approx(1.0, abs=0.02)
    assert as_cost["lower_is_better"] is True and as_share["lower_is_better"] is False


def test_direction_names_the_winner_for_both_meanings_of_better():
    # Arrange: A minus B wholly below zero, wholly above zero, and across zero
    below, above, across = {"lo": -5.0, "hi": -1.0}, {"lo": 1.0, "hi": 5.0}, {"lo": -1.0, "hi": 5.0}
    touching = {"lo": 0.0, "hi": 5.0}

    # Act / Assert: lower is better (a cost): A below B is a win for A
    assert direction({**below, "lower_is_better": True}) == "a better"
    assert direction({**above, "lower_is_better": True}) == "b better"
    assert direction({**across, "lower_is_better": True}) == "not separated"
    # higher is better (a share): A above B is a win for A
    assert direction({**below, "lower_is_better": False}) == "b better"
    assert direction({**above, "lower_is_better": False}) == "a better"
    assert direction({**across, "lower_is_better": False}) == "not separated"
    assert direction({**touching, "lower_is_better": False}) == "not separated"
    # and on a real result: A is 2 lower every year, which is a win only if lower is better
    lower = COST_B - 2
    assert direction(year_block_bootstrap(lower, COST_B, draws=200, lower_is_better=True)) == "a better"
    assert direction(year_block_bootstrap(lower, COST_B, draws=200, lower_is_better=False)) == "b better"


def test_weighted_interval_equals_a_hand_loop_over_the_same_resampled_years():
    # Arrange: yearly mean errors and row counts; redo the resampling by hand, one draw at a time
    a = COST_A / 10
    b = COST_B / 10
    rows = pd.Series([31, 31, 30, 29, 31, 28, 31, 31, 27, 31, 30, 31], index=YEARS, dtype=float)
    picked = resample_years(len(YEARS), 400, np.random.default_rng(7), block=1)
    by_hand = []
    for draw in picked:
        total = sum(rows.iloc[i] for i in draw)
        mean_a = sum(a.iloc[i] * rows.iloc[i] for i in draw) / total
        mean_b = sum(b.iloc[i] * rows.iloc[i] for i in draw) / total
        by_hand.append(mean_a - mean_b)

    # Act
    result = year_block_bootstrap(a, b, weights=rows, draws=400, seed=7, lower_is_better=True)

    # Assert
    assert result["lo"] == pytest.approx(np.percentile(by_hand, 2.5))
    assert result["hi"] == pytest.approx(np.percentile(by_hand, 97.5))
    assert result["share_draws_a_better"] == pytest.approx(np.mean([d < 0 for d in by_hand]))


def test_interval_ends_are_the_2_5_and_97_5_percentiles():
    # Arrange: the same draws by hand, in sum mode
    picked = resample_years(len(YEARS), 1000, np.random.default_rng(3), block=1)
    sums = (COST_A.to_numpy() - COST_B.to_numpy())[picked].sum(axis=1)

    # Act
    result = year_block_bootstrap(COST_A, COST_B, draws=1000, seed=3, lower_is_better=True)

    # Assert: a 90% interval (5 and 95) would be narrower at both ends, and is not what we return
    assert (result["lo"], result["hi"]) == (np.percentile(sums, 2.5), np.percentile(sums, 97.5))
    assert result["lo"] < np.percentile(sums, 5) and result["hi"] > np.percentile(sums, 95)


def test_every_result_carries_the_caveat_with_its_own_numbers():
    # Arrange / Act
    eight = year_block_bootstrap(COST_A[:8], COST_B[:8], draws=100, block=2, lower_is_better=True)
    twelve = year_block_bootstrap(COST_A, COST_B, draws=100, lower_is_better=True)

    # Assert
    assert eight["caveat"].startswith("Percentile interval from 8 resampled years (block 2). With this few")
    assert twelve["caveat"].startswith("Percentile interval from 12 resampled years (block 1).")
    assert "88% of the time with 8 years and 92% with 18 (80% and 90% with two-year blocks)" in twelve["caveat"]


def test_mismatched_years_raise_an_error_that_names_them():
    # Arrange
    a = {2001: 1.0, 2002: 2.0}
    b = {2001: 1.0, 2003: 2.0}

    # Act / Assert
    with pytest.raises(ValueError, match="2002") as error:
        year_block_bootstrap(a, b, lower_is_better=True)
    assert "2003" in str(error.value)
    with pytest.raises(ValueError, match="weights"):
        year_block_bootstrap(a, a, weights={2001: 5}, lower_is_better=True)


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


# ---------------------------------------------------------------------------------------------
# A made-up scored outlook table, shared by the trigger and allocation tests
# ---------------------------------------------------------------------------------------------
def scored_table(years=range(2008, 2014), months=(1, 2, 3)):
    """Made-up scored outlook rows: 31 Rio Grande counties (6 of them matched to a reservoir)
    and 2 Ohio counties, one row per county per issue month. No random numbers."""
    fips = sorted(COUNTY_RESERVOIR)[:6] + [f"99{i:03d}" for i in range(27)]
    rows = []
    for year in years:
        for month in months:
            for i, code in enumerate(fips):
                dryness = (3 * year + 7 * month + 5 * i) % 24                 # 0..23
                rows.append({"date": pd.Timestamp(year=year, month=month, day=4), "fips": code,
                             "river": "Rio Grande" if i < 31 else "Ohio", "cls": dryness // 4,
                             "d2_streak": float(max(dryness - 11, 0)), "mean12": dryness / 5,
                             "p_season": round(dryness / 24, 4),
                             "p_season_res": round(((dryness + 2) % 24) / 24, 4),
                             "y_season": float(dryness + (year + i) % 7 >= 16)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# trigger.run_trigger_annual (section 3.2)
# ---------------------------------------------------------------------------------------------
def test_trigger_annual_has_one_row_per_county_year():
    # Arrange: 31 Rio Grande counties, 6 years, issued in January, February and March
    scored = scored_table()

    # Act
    annual = run_trigger_annual(scored)
    three_months = run_trigger(scored)

    # Assert: 31 x 6 county-years, a third of the three-month table, Ohio rows left out
    assert annual["rows"] == annual["county_years"] == 31 * 6
    assert three_months["rows"] == 3 * annual["rows"]
    assert annual["issue_month"] == 3 and annual["years"] == 6
    march = scored[(scored["river"] == "Rio Grande") & (scored["date"].dt.month == 3)]
    assert annual["drought_seasons"] == int(march["y_season"].sum())


def test_trigger_annual_refuses_two_rows_for_one_county_year():
    # Arrange: the same county issued twice in March 2008
    scored = scored_table()
    doubled = pd.concat([scored, scored[scored["date"] == "2008-03-04"].head(1)], ignore_index=True)

    # Act / Assert
    with pytest.raises(AssertionError, match="county-years"):
        run_trigger_annual(doubled)


def test_trigger_annual_marks_only_the_two_new_rules_as_added():
    # Arrange
    scored = scored_table()
    march = scored[(scored["river"] == "Rio Grande") & (scored["date"].dt.month == 3)]

    # Act
    annual = run_trigger_annual(scored)
    added = [rule for rule in annual["rules"] if rule.get("added")]

    # Assert: the five old rules come first, unmarked, then the two new ones
    assert [rule["name"] for rule in annual["rules"][:5]] == [rule["name"] for rule in run_trigger(scored)["rules"]]
    assert [rule["name"] for rule in added] == ["D0 or worse now", "Class-conditional frequency"]
    assert added[0]["fires"] == int((march["cls"] >= 1).sum())            # D0 is class 1
    assert all(set(annual["added_sweep_keys"]) <= set(line) for line in annual["value_sweep"])


def test_trigger_annual_class_frequency_needs_a_past():
    # Arrange: the scored rows start in 2008; a history that starts in 2005 knows the years before
    scored = scored_table()
    history = scored_table(years=range(2005, 2014))

    # Act
    alone = run_trigger_annual(scored)
    with_history = run_trigger_annual(scored, history=history)

    # Assert: with no earlier years the 31 rows of March 2008 have no frequency and cannot fire
    assert alone["class_frequency_rows_without_past"] == 31
    assert with_history["class_frequency_rows_without_past"] == 0
    assert with_history["rules"][-1]["fires"] > alone["rules"][-1]["fires"]
    assert with_history["rules"][:6] == alone["rules"][:6]                # nothing else moves


def test_run_trigger_output_is_unchanged_by_the_annual_addition():
    # Arrange: this fingerprint of run_trigger's output on the made-up table was taken from
    # trigger.py as it stood BEFORE run_trigger_annual was added (commit 7196200).
    before = "27a2c44564445ce2db69282940a16cfbb19a802e3ce6a7a8492d79571d2d234f"

    # Act
    result = run_trigger(scored_table())
    after = hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest()

    # Assert
    assert after == before
    assert result["issue_months"] == [1, 2, 3] and "county_years" not in result


# ---------------------------------------------------------------------------------------------
# allocation.py (section 3.4)
# ---------------------------------------------------------------------------------------------
def march_table(per_year):
    """Rows for run_allocation from {year: [(fips, p_season, cls, d2_streak, mean12, y_season), ...]}."""
    return pd.DataFrame([{"date": pd.Timestamp(year=year, month=3, day=2), "river": "Rio Grande", "fips": fips,
                          "p_season": p, "cls": cls, "d2_streak": streak, "mean12": mean12, "y_season": y}
                         for year, counties in per_year.items()
                         for fips, p, cls, streak, mean12, y in counties])


FIVE_COUNTIES = {
    2010: [("00001", 0.9, 2, 0, 1.0, 0), ("00002", 0.8, 4, 5, 3.0, 1), ("00003", 0.8, 4, 2, 3.5, 1),
           ("00004", 0.1, 4, 5, 2.0, 0), ("00005", 0.5, 1, 0, 0.5, 1)],
    2011: [("00001", 0.2, 0, 0, 0.0, 0), ("00002", 0.7, 3, 1, 2.0, 1), ("00003", 0.6, 3, 4, 1.0, 0),
           ("00004", 0.9, 2, 0, 2.5, 1), ("00005", 0.3, 0, 0, 0.2, 0)],
}


def funded_sets(result):
    """{(k, ranking): the funded FIPS codes, year by year} - who got the money, nothing else."""
    return {(entry["k"], name): codes for entry in result["per_k"] for name, codes in entry["funded"].items()}


def test_allocation_matches_a_hand_worked_example_and_breaks_ties_by_fips():
    # Arrange: five counties, two years, worked out by hand.
    # 2010 model order: 00001 (0.9), then 00002 before 00003 (both 0.8, lower FIPS first).
    # 2010 rule A: class 4 first; 00002 and 00004 both have a streak of 5, so 00002 then 00004.
    # 2010 rule B: class 4 first, by 12-week average: 00003 (3.5), 00002 (3.0), 00004 (2.0).
    # 2011: model 00004, 00002, 00003; rule A 00003, 00002, 00004; rule B 00002, 00003, 00004.
    table = march_table(FIVE_COUNTIES)

    # Act
    result = run_allocation(table, ks=(1, 2, 3), draws=200)
    k1, k2, k3 = result["per_k"]

    # Assert
    assert result["years"] == [2010, 2011] and result["rows"] == 10 and result["counties_per_year"] == [5, 5]
    assert k2["funded"] == {"model": [["00001", "00002"], ["00004", "00002"]],
                            "rule_a": [["00002", "00004"], ["00003", "00002"]],
                            "rule_b": [["00003", "00002"], ["00002", "00003"]]}
    assert k1["per_year"]["model"] == [0.0, 1.0] and k1["per_year"]["rule_a"] == [1.0, 0.0]
    assert k1["per_year"]["rule_b"] == [1.0, 1.0]
    assert k2["per_year"]["model"] == [0.5, 1.0] and k2["per_year"]["rule_b"] == [1.0, 0.5]
    assert k3["per_year"]["model"] == pytest.approx([2 / 3, 2 / 3])
    assert k2["mean"]["model"] == 0.75 and k2["mean"]["rule_a"] == 0.5 and k2["mean"]["rule_b"] == 0.75
    # the better rule is chosen once per k from its mean over both years: B, B, then A on a tie
    assert [entry["better_rule"] for entry in result["per_k"]] == ["rule_b", "rule_b", "rule_a"]
    assert k1["model_minus_better_rule"]["per_year"] == [-1.0, 0.0]
    assert k1["model_minus_better_rule"]["mean"] == -0.5
    assert k1["model_minus_better_rule"]["interval"]["diff"] == -0.5
    # averaged over k: model (0 + 1/2 + 2/3) / 3 in 2010 and (1 + 1 + 2/3) / 3 in 2011
    average = result["average_over_k"]
    assert average["per_year"]["model"] == pytest.approx([7 / 18, 16 / 18])
    assert average["better_rule"] == "rule_b"
    assert average["model_minus_better_rule"]["mean"] == pytest.approx(23 / 36 - 29 / 36)
    assert json.loads(json.dumps(result)) == result


def test_allocation_random_is_the_base_rate_and_the_oracle_is_never_beaten():
    # Arrange
    table = march_table(FIVE_COUNTIES)

    # Act
    result = run_allocation(table, ks=(1, 2, 3, 4, 5), draws=200)

    # Assert: 3 of 5 counties had a drought season in 2010 and 2 of 5 in 2011
    for entry in result["per_k"]:
        assert entry["per_year"]["random"] == [0.6, 0.4]
        for name in ("model", "rule_a", "rule_b", "random"):
            assert all(o >= s for o, s in zip(entry["per_year"]["oracle"], entry["per_year"][name]))
    assert result["per_k"][3]["per_year"]["oracle"] == [0.75, 0.5]       # k = 4: 3 of 4, then 2 of 4
    funding_everyone = result["per_k"][4]["per_year"]
    assert funding_everyone["model"] == funding_everyone["oracle"] == funding_everyone["random"]


def test_allocation_ranks_use_only_issue_date_columns():
    # Arrange: the made-up scored table, then one copy with every answer turned round and one
    # copy with every other column that is not a ranking column rewritten or added
    scored = scored_table()
    answers_flipped = scored.assign(y_season=1 - scored["y_season"])
    others_changed = scored.assign(p_season_res=0.5, y_weeks=13.0, county="Somewhere", p_season_usual=0.9,
                                   weeks_model=scored["p_season"].rank(ascending=True))

    # Act
    original = run_allocation(scored, draws=200)
    flipped = run_allocation(answers_flipped, draws=200)
    changed = run_allocation(others_changed, draws=200)

    # Assert: the answers move the scores but never who is funded; other columns move nothing
    assert funded_sets(flipped) == funded_sets(original)
    assert flipped["per_k"][0]["per_year"] != original["per_k"][0]["per_year"]
    assert changed == original
    assert original["rows"] == 31 * 6 and all(len(codes) == 6 for codes in funded_sets(original).values())


def test_allocation_reports_a_model_that_funds_better_as_above_zero():
    # Arrange: six years in which the forecast puts the two drought counties first and both rules
    # put them last (their class is the lowest). Higher share is better, so the model wins.
    per_year = {year: [("00001", 0.9, 0, 0, 0.0, 1), ("00002", 0.8, 0, 0, 0.1, 1),
                       ("00003", 0.2, 3, 4, 2.0, 0), ("00004", 0.1, 4, 6, 3.0, 0)]
                for year in range(2010, 2016)}

    # Act
    result = run_allocation(march_table(per_year), ks=(2,), draws=500)
    gap = result["per_k"][0]["model_minus_better_rule"]

    # Assert: model share 1, rule share 0, so model minus rule is +1 with the interval above zero
    assert gap["mean"] == 1.0 and gap["interval"]["diff"] == 1.0
    assert gap["interval"]["lo"] == gap["interval"]["hi"] == 1.0
    assert gap["interval"]["share_draws_model_better"] == 1.0 and gap["interval"]["years_model_better"] == 6
    assert gap["interval"]["higher_is_better"] is True and excludes_zero(gap["interval"]) is True


def test_model_minus_rule_interval_is_in_plain_shares_with_low_below_high():
    # Arrange: the model is better in three years of four, by different amounts
    years = [2010, 2011, 2012, 2013]
    model = pd.Series([0.8, 0.6, 0.4, 0.9], index=years)
    rule = pd.Series([0.5, 0.5, 0.6, 0.3], index=years)

    # Act
    interval = model_minus_rule(model, rule, draws=2000, seed=0)

    # Assert: mean gap (0.3 + 0.1 - 0.2 + 0.6) / 4 = 0.2, inside an interval that is the right way up
    assert interval["diff"] == pytest.approx(0.2)
    assert -0.2 <= interval["lo"] < interval["diff"] < interval["hi"] <= 0.6
    assert interval["years_model_better"] == 3 and interval["share_draws_model_better"] > 0.5


def test_allocation_refuses_a_budget_larger_than_the_number_of_counties():
    with pytest.raises(ValueError, match="cannot fund"):
        run_allocation(march_table(FIVE_COUNTIES), ks=(6,), draws=10)
