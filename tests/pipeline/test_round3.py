"""Tests for the round 3 evaluation work (ARCHITECTURE.md section 3).

The tables in the first sections are small and made up. Only the last section, the freeze,
reads the real files, and it never scores anything: it checks that what is on disk agrees."""
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

import inspect

from farmdrought import alert as alert_module
from farmdrought import config, export, refresh, robustness, round3, v2
from farmdrought.allocation import model_minus_rule, run_allocation
from farmdrought.config import (ALERT_WEEKS, COUNTY_RESERVOIR, FROZEN, METRICS, OUTLOOK, PREDICTIONS, SCORE_THROUGH,
                                SEASON_WEEKS, YEAR_WEEKS)
from farmdrought.drought import build_panel, load_usdm
from farmdrought.leaks import bed_layer, seepage_rate, water_table_factor
from farmdrought.manifest import build_manifest, check_manifest, guard_scored_writer, sha256_of
from farmdrought.prob_calibration import (brier, calibrate_by_past, calibration_coverage, class_frequency_by_past,
                                          reliability)
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
    assert year_block_bootstrap(two_a, two_b, draws=200, lower_is_better=True)["n_years"] == 2


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
    eight = year_block_bootstrap(COST_A[:8], COST_B[:8], draws=200, block=2, lower_is_better=True)
    twelve = year_block_bootstrap(COST_A, COST_B, draws=200, lower_is_better=True)

    # Assert
    assert eight["caveat"].startswith("Percentile interval from 8 resampled years (block 2). With this few")
    assert twelve["caveat"].startswith("Percentile interval from 12 resampled years (block 1).")
    assert "88% of the time with 8 years and 92% with 18 (80% and 90% with two-year blocks)" in twelve["caveat"]
    assert "is expected to be less if years are dependent" in twelve["caveat"]
    # the reader is told where the coverage figures come from
    assert twelve["caveat"].endswith("a simulation with independent years and a true difference of zero, "
                                     "not from this project's data.")


def test_too_few_draws_are_refused():
    # Arrange / Act / Assert: 199 resamples are refused, 200 are accepted
    with pytest.raises(ValueError, match="at least 200"):
        year_block_bootstrap(COST_A, COST_B, draws=199, lower_is_better=True)
    assert year_block_bootstrap(COST_A, COST_B, draws=200, lower_is_better=True)["draws"] == 200


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
    assert gap["interval"]["lower_is_better"] is False and direction(gap["interval"]) == "a better"


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


# ---------------------------------------------------------------------------------------------
# Reporting gaps found in review (package F, step 1)
# ---------------------------------------------------------------------------------------------
def tiny_calibration_table():
    """Eight past forecasts in January 2001, 2002 and 2003, then six forecasts in 2005.
    Pooled past: 0.1 -> answers 1, 0;  0.3 -> 0, 0;  0.7 -> 1, 1, 0, 1."""
    past = [("2001-01-02", 0.1, 1), ("2001-01-02", 0.3, 0), ("2001-01-02", 0.7, 1),
            ("2002-01-01", 0.1, 0), ("2002-01-01", 0.3, 0), ("2002-01-01", 0.7, 1),
            ("2003-01-07", 0.7, 0), ("2003-01-07", 0.7, 1)]
    new = [("2005-03-01", p, 0) for p in (0.05, 0.1, 0.3, 0.5, 0.7, 0.95)]
    return pd.DataFrame([{"date": pd.Timestamp(d), "p": p, "y": float(y)} for d, p, y in past + new])


def test_calibration_gives_the_hand_computed_values_on_a_tiny_example():
    # Arrange: by hand, the yes-rate is 1/2 at 0.1, 0/2 at 0.3 and 3/4 at 0.7. A curve that may
    # only go up cannot drop from 1/2 to 0, so 0.1 and 0.3 are pooled: 1 yes in 4 = 0.25.
    # So the curve is 0.25 up to 0.3, 0.75 from 0.7, and a straight line between them.
    table = tiny_calibration_table()

    # Act
    calibrated = calibrate_by_past(table, "p", "y", horizon=26)

    # Assert: 0.05 and 0.95 lie outside the past forecasts and take the nearest end value;
    # 0.5 is halfway between 0.3 and 0.7, so halfway between 0.25 and 0.75
    in_2005 = table["date"].dt.year == 2005
    assert calibrated[in_2005].tolist() == pytest.approx([0.25, 0.25, 0.25, 0.5, 0.75, 0.75])
    assert calibrated[~in_2005].equals(table.loc[~in_2005, "p"])        # too little past: left raw


def test_calibration_coverage_names_the_years_left_raw():
    # Arrange
    table = tiny_calibration_table()

    # Act
    coverage = calibration_coverage(table, "p", "y", horizon=26)

    # Assert: 2001 has no past, 2002 one year (3 rows), 2003 two years (6 rows), 2005 three (8 rows)
    assert coverage["years"] == [
        {"year": 2001, "status": "raw", "calibrated": False, "forecasts": 3, "past_years": 0, "past_rows": 0},
        {"year": 2002, "status": "raw", "calibrated": False, "forecasts": 3, "past_years": 1, "past_rows": 3},
        {"year": 2003, "status": "raw", "calibrated": False, "forecasts": 2, "past_years": 2, "past_rows": 6},
        {"year": 2005, "status": "calibrated", "calibrated": True, "forecasts": 6, "past_years": 3, "past_rows": 8}]
    assert coverage["years_left_raw"] == [2001, 2002, 2003] and coverage["min_years"] == 3
    assert coverage["years_without_forecast"] == []
    # with a lower bar, 2003 is calibrated too, and the Series agrees with the coverage
    assert calibration_coverage(table, "p", "y", horizon=26, min_years=2)["years_left_raw"] == [2001, 2002]
    lower_bar = calibrate_by_past(table, "p", "y", horizon=26, min_years=2)
    in_2003 = table["date"].dt.year == 2003
    assert not lower_bar[in_2003].equals(table.loc[in_2003, "p"])
    assert json.loads(json.dumps(coverage)) == coverage


def test_calibration_passes_over_a_year_that_has_no_forecast_at_all():
    # Arrange: the newest year has rows but no forecast yet (the real table ends like this)
    table = tiny_calibration_table()
    newest = pd.DataFrame({"date": pd.to_datetime(["2006-02-07", "2006-03-07"]), "p": [np.nan, np.nan], "y": [np.nan, np.nan]})
    table = pd.concat([table, newest], ignore_index=True)

    # Act
    calibrated = calibrate_by_past(table, "p", "y", horizon=26)

    coverage = calibration_coverage(table, "p", "y", horizon=26)

    # Assert: the empty year stays missing and the year before it is calibrated as before
    assert calibrated[table["date"].dt.year == 2006].isna().all()
    assert calibrated[table["date"].dt.year == 2005].tolist() == pytest.approx([0.25, 0.25, 0.25, 0.5, 0.75, 0.75])
    # and the coverage calls it "no forecast": not calibrated, and not left raw either
    last = coverage["years"][-1]
    assert (last["year"], last["status"], last["calibrated"], last["forecasts"]) == (2006, "no forecast", False, 0)
    assert coverage["years_without_forecast"] == [2006] and 2006 not in coverage["years_left_raw"]


def tiny_trigger_tables():
    """Three Rio Grande counties scored in March 2008 (classes 0, 2 and 4), and a history that
    also holds March 2005 and 2006: class 0 twice (no drought season), class 2 five times (one
    drought season) and class 4 twice (both drought seasons)."""
    def row(date, fips, cls, y, p=0.5):
        return {"date": pd.Timestamp(date), "fips": fips, "river": "Rio Grande", "cls": cls,
                "y_season": float(y), "p_season": p, "p_season_res": p}
    earlier = [row("2005-03-01", "99001", 0, 0), row("2005-03-01", "99002", 2, 0), row("2005-03-01", "99003", 2, 1),
               row("2005-03-01", "99004", 2, 0), row("2005-03-01", "99005", 4, 1),
               row("2006-03-07", "99001", 0, 0), row("2006-03-07", "99002", 2, 0), row("2006-03-07", "99003", 2, 0),
               row("2006-03-07", "99005", 4, 1)]
    scored = [row("2008-03-04", "99001", 0, 0), row("2008-03-04", "99002", 2, 1), row("2008-03-04", "99005", 4, 1)]
    return pd.DataFrame(scored), pd.DataFrame(earlier + scored)


def test_class_frequency_rule_fires_and_sweeps_as_worked_out_by_hand():
    # Arrange: from the history, P(drought season | class) is 0/2 = 0 for class 0,
    # 1/5 = 0.2 for class 2 and 2/2 = 1 for class 4. Two of the three scored counties had one.
    scored, history = tiny_trigger_tables()

    # Act
    result = run_trigger_annual(scored, history=history)
    rule = result["rules"][-1]
    sweep = {line["cost_ratio"]: line["class_frequency"] for line in result["value_sweep"]}

    # Assert: at the 0.25 threshold only class 4 fires (0.2 is below it): 1 fired, 1 caught, 1 missed
    assert rule["name"] == "Class-conditional frequency" and rule["added"] is True
    assert (rule["fires"], rule["caught"], rule["missed"], rule["false_alarms"]) == (1, 1, 1, 0)
    # In the sweep it fires when the frequency is at least the cost ratio. Up to 0.18 classes 2
    # and 4 fire (2 caught, 2 firings); at 0.25 and 0.5 only class 4 (1 caught, 1 firing).
    # value = (caught - ratio x firings) / 3 rows
    assert sweep == {0.02: round((2 - 0.02 * 2) / 3, 4), 0.05: round((2 - 0.05 * 2) / 3, 4),
                     0.10: round((2 - 0.10 * 2) / 3, 4), 0.18: round((2 - 0.18 * 2) / 3, 4),
                     0.25: round((1 - 0.25) / 3, 4), 0.50: round((1 - 0.50) / 3, 4)}
    assert result["class_frequency_rows_without_past"] == 0
    assert result["class_frequency_rows_absent_from_history"] == 0


def test_trigger_annual_tells_no_past_apart_from_rows_missing_in_the_history():
    # Arrange
    scored, history = tiny_trigger_tables()
    earlier_only = history[history["date"] < "2008-01-01"]            # the scored rows are not in it

    # Act
    alone = run_trigger_annual(scored)                                 # the scored rows are their own history
    wrong_table = run_trigger_annual(scored, history=earlier_only)

    # Assert
    assert (alone["class_frequency_rows_without_past"], alone["class_frequency_rows_absent_from_history"]) == (3, 0)
    assert (wrong_table["class_frequency_rows_without_past"],
            wrong_table["class_frequency_rows_absent_from_history"]) == (0, 3)
    assert alone["rules"][-1]["fires"] == wrong_table["rules"][-1]["fires"] == 0


def test_trigger_annual_history_never_uses_an_answer_whose_window_was_still_open():
    # Arrange: a history from 2005 on. Rewrite, in the HISTORY only, every answer of 2013 (the
    # last scored year) and every answer of 2012 issued late enough that its 26-week window was
    # still open on 1 January 2013. The scored table keeps the true answers.
    scored = scored_table()
    history = scored_table(years=range(2005, 2014), months=(1, 2, 3, 8, 11))
    still_open = history["date"] + pd.Timedelta(weeks=26) >= pd.Timestamp("2013-01-01")
    rewritten = history.copy()
    rewritten.loc[still_open, "y_season"] = 1 - rewritten.loc[still_open, "y_season"]
    closed_in_2012 = (history["date"].dt.year == 2012) & ~still_open
    control = history.copy()
    control.loc[closed_in_2012, "y_season"] = 1 - control.loc[closed_in_2012, "y_season"]

    # Act
    original = run_trigger_annual(scored, history=history)
    with_open_answers_rewritten = run_trigger_annual(scored, history=rewritten)
    with_closed_answers_rewritten = run_trigger_annual(scored, history=control)

    # Assert: answers not yet known change nothing; answers that were known do
    assert int(still_open.sum()) > 31 * 3                             # 2013, and late 2012
    assert with_open_answers_rewritten == original
    assert with_closed_answers_rewritten["value_sweep"] != original["value_sweep"]


THREE_YEARS = {**FIVE_COUNTIES,
               2012: [("00001", 0.9, 4, 3, 2.0, 0), ("00002", 0.8, 3, 0, 1.0, 0), ("00003", 0.1, 0, 0, 0.0, 0),
                      ("00004", 0.2, 1, 0, 0.5, 0), ("00005", 0.3, 2, 0, 0.7, 0)]}   # no county had a drought season


def test_allocation_reports_the_model_against_each_rule_and_flags_the_better_rule_pick():
    # Arrange: the five-county example. For k = 1 the shares are model 0, 1; rule A 1, 0; rule B 1, 1.
    table = march_table(FIVE_COUNTIES)

    # Act
    result = run_allocation(table, ks=(1, 2, 3), draws=200)
    k1, average = result["per_k"][0], result["average_over_k"]

    # Assert: both rules get their own comparison, each with an interval
    assert k1["model_minus_rule_a"]["per_year"] == [-1.0, 1.0] and k1["model_minus_rule_a"]["mean"] == 0.0
    assert k1["model_minus_rule_b"]["per_year"] == [-1.0, 0.0] and k1["model_minus_rule_b"]["mean"] == -0.5
    for block in (k1, average):
        for name in ("model_minus_rule_a", "model_minus_rule_b", "model_minus_better_rule"):
            interval = block[name]["interval"]
            assert interval["lo"] <= interval["diff"] <= interval["hi"] and interval["n_years"] == 2
            assert interval["diff"] == pytest.approx(block[name]["mean"]) and "caveat" in interval
    # the better rule's comparison is the same numbers as that rule's own, plus the warning
    assert k1["better_rule"] == "rule_b"
    assert k1["model_minus_better_rule"]["interval"] == k1["model_minus_rule_b"]["interval"]
    note = k1["model_minus_better_rule"]["note"]
    assert "picked AFTER seeing both" in note and "7.7%" in note and "1.3%" in note
    assert "400 repetitions, k = 15, 18 years" in note and "not this project's data" in note
    assert "note" not in k1["model_minus_rule_a"] and "note" in average["model_minus_better_rule"]


def test_allocation_counts_the_years_where_the_choice_could_matter():
    # Arrange: a third year, 2012, in which no county had a drought season: every ranking scores 0
    table = march_table(THREE_YEARS)

    # Act
    result = run_allocation(table, ks=(1, 5), draws=200)
    k1, k5 = [entry["years_where_choice_mattered"] for entry in result["per_k"]]

    # Assert: with k = 1, random (0.6, 0.4, 0) and oracle (1, 1, 0) differ in 2010 and 2011 only.
    # Over those two years the model is level with rule A (-1, +1) and behind rule B (-1, 0).
    assert (k1["n"], k1["years"]) == (2, [2010, 2011])
    assert k1["model_minus_rule_a_mean"] == 0.0 and k1["model_minus_rule_b_mean"] == -0.5
    assert result["per_k"][0]["model_minus_rule_b"]["mean"] == pytest.approx(-1 / 3)   # all three years
    assert k1["label"].startswith("Descriptive only")
    # with k = 5 every county is funded, so no year can matter and there is no mean to give
    assert (k5["n"], k5["years"], k5["model_minus_rule_a_mean"], k5["model_minus_rule_b_mean"]) == (0, [], None, None)


# ---------------------------------------------------------------------------------------------
# round3.py: the scoring script (package F, step 2). Made-up tables only; it is never run here
# on the real data.
# ---------------------------------------------------------------------------------------------
def outlook_rows():
    """The made-up scored table with the extra columns the 6- and 12-month comparisons read."""
    table = scored_table()
    table = table[table["river"] == "Rio Grande"].reset_index(drop=True)
    dryness = table["mean12"] * 5
    return table.assign(alarm_season_persistence=table["cls"] >= 3, alarm_season_d1=table["cls"] >= 2,
                        p_season_usual=0.3, y_weeks=(dryness * 2).clip(upper=52),
                        weeks_model=dryness * 2 + 3, weeks_same_as_now=np.where(table["cls"] >= 3, 52.0, 0.0),
                        weeks_last_year=dryness, weeks_usual=20.0)


def test_round3_writes_one_file_per_item_and_refuses_to_replace_any(tmp_path):
    # Arrange
    folder = tmp_path / "round3"
    first = {"intervals_v1.json": {"added": True, "n": 1}, "allocation.json": {"added": True, "n": 2}}

    # Act
    written = round3.write_items(first, folder=folder)

    # Assert: both files exist with their content
    assert sorted(path.name for path in written) == ["allocation.json", "intervals_v1.json"]
    assert json.loads((folder / "allocation.json").read_text()) == {"added": True, "n": 2}
    # a second run that would replace one of them writes NOTHING, not even the new file
    with pytest.raises(RuntimeError, match="already scored.*allocation.json.*--force"):
        round3.write_items({"allocation.json": {"n": 99}, "calibration.json": {"n": 3}}, folder=folder)
    assert json.loads((folder / "allocation.json").read_text())["n"] == 2
    assert not (folder / "calibration.json").exists()
    # with force it is replaced
    round3.write_items({"allocation.json": {"n": 99}}, folder=folder, force=True)
    assert json.loads((folder / "allocation.json").read_text())["n"] == 99


def test_round3_main_refuses_before_scoring_when_a_result_exists(tmp_path, monkeypatch):
    # Arrange: one result file is already there; scoring must never start
    (tmp_path / "trigger_annual.json").write_text("{}")
    monkeypatch.setattr(round3, "ROUND3", tmp_path)
    monkeypatch.setattr(round3, "run_alert", lambda **kwargs: pytest.fail("round3 went on to score"))

    # Act / Assert
    with pytest.raises(RuntimeError, match="already scored.*trigger_annual.json"):
        round3.main()
    assert (tmp_path / "trigger_annual.json").read_text() == "{}"


def test_round3_comparison_holds_every_year_and_agrees_with_the_totals():
    # Arrange: yearly costs for a system and a rule over six years; the system is lower in four
    years = range(2010, 2016)
    system = pd.Series([10, 12, 8, 20, 5, 9], index=years, dtype=float)
    rule = pd.Series([14, 11, 12, 25, 4, 15], index=years, dtype=float)

    # Act
    entry = round3.compare("system cost minus rule", system, rule, None, True, "made-up rows", b_name="D1 now")

    # Assert
    assert entry["per_year"] == {"years": list(years), "system": list(system), "D1 now": list(rule)}
    assert (entry["system_total"], entry["D1 now_total"], entry["difference"]) == (64.0, 81.0, -17.0)
    assert entry["block1"]["n_years"] == 6 and entry["block1"]["block"] == 1 and entry["block2"]["block"] == 2
    assert entry["block1"]["years_a_better"] == 4 and entry["block1"]["draws"] == 10000
    assert entry["block1"]["direction"] in ("system better", "D1 now better", "not separated")
    assert "caveat" in entry["block1"] and entry["year_unit"].startswith("the calendar year of the issue date")
    # an odd number of years has no block-2 interval, and says why
    odd = round3.compare("x", system[:5], rule[:5], None, True, "made-up rows")
    assert odd["block2"] == "not computed: block 2 needs an even number of years"


def test_round3_direction_words_follow_the_interval():
    # Arrange: the system is 5 lower every year, then 5 higher every year
    years = range(2010, 2016)
    rule = pd.Series([14, 11, 12, 25, 4, 15], index=years, dtype=float)

    # Act
    win = round3.compare("x", rule - 5, rule, None, True, "made-up rows")
    loss = round3.compare("x", rule + 5, rule, None, True, "made-up rows")
    share_win = round3.compare("x", rule + 5, rule, None, False, "made-up rows", a_name="forecast", b_name="D1")

    # Assert
    assert win["block1"]["direction"] == "system better" and loss["block1"]["direction"] == "rule better"
    assert share_win["block1"]["direction"] == "forecast better"


def test_round3_outlook_comparisons_add_up_to_the_whole_table_scores():
    # Arrange
    rows = outlook_rows()

    # Act
    season = {entry["b"]: entry for entry in round3.season_comparisons(rows)}
    year = {entry["b"]: entry for entry in round3.year_comparisons(rows)}

    # Assert: the yearly costs sum to the cost of the whole table, for the system and for each rule
    y = rows["y_season"]
    assert sorted(season) == ["Always warn", "D1 now", "Never warn", "Persistence", "Usual"]
    assert season["D1 now"]["system_total"] == tally_cost(y, rows["p_season"] >= 0.25)
    assert season["D1 now"]["D1 now_total"] == tally_cost(y, rows["cls"] >= 2)
    assert season["Never warn"]["Never warn_total"] == 3 * int(y.sum())
    assert season["Always warn"]["Always warn_total"] == int((y == 0).sum())
    assert len(season["D1 now"]["per_year"]["years"]) == 6
    # the 12-month error is a mean over rows: yearly means weighted by rows give the table's mean
    assert sorted(year) == ["Last year", "Same as now", "Usual"]
    assert year["Usual"]["system_mean"] == pytest.approx((rows["weeks_model"] - rows["y_weeks"]).abs().mean())
    assert year["Usual"]["Usual_mean"] == pytest.approx((rows["weeks_usual"] - rows["y_weeks"]).abs().mean())
    assert year["Usual"]["per_year"]["rows"] == [31 * 3] * 6


def tally_cost(y, alarm):
    """3 x missed + false alarms, written out here so the test does not lean on the code it checks."""
    y, alarm = np.asarray(y) == 1, np.asarray(alarm, dtype=bool)
    return float(3 * (y & ~alarm).sum() + (~y & alarm).sum())


def test_round3_trigger_values_by_year_average_to_the_annual_table():
    # Arrange
    scored = scored_table()
    history = scored_table(years=range(2005, 2014))

    # Act
    item = round3.trigger_item(scored, history)
    sweep = {line["cost_ratio"]: line for line in item["table"]["value_sweep"]}

    # Assert: three comparisons at each of the six cost ratios, two of them against ADDED rules
    assert len(item["value_differences"]) == 18
    assert sum(entry["rule_is_added"] for entry in item["value_differences"]) == 12
    keys = {"D1 or worse now": "d1_rule", "D0 or worse now": "d0_rule", "Class-conditional frequency": "class_frequency"}
    for entry in item["value_differences"]:
        line = sweep[entry["cost_ratio"]]
        # the mean over decisions of the yearly values is the value in the annual table
        assert entry["forecast_mean"] == pytest.approx(line["forecast"], abs=5e-5)
        assert entry[entry["rule"] + "_mean"] == pytest.approx(line[keys[entry["rule"]]], abs=5e-5)
        assert entry["lower_is_better"] is False and entry["per_year"]["rows"] == [31] * 6
        assert entry["block1"]["direction"] in ("forecast better", entry["rule"] + " better", "not separated")


def test_round3_calibration_item_scores_all_four_probabilities_on_the_same_rows():
    # Arrange: a made-up history with a chained forecast from 2001, and the "scored" rows from 2005
    history = forecast_table().rename(columns={"p": "p_chain", "y": "y_season"})
    scored = history[history["date"].dt.year >= 2005].rename(columns={"p_chain": "p_season"}).assign(p_season_usual=0.4)

    # Act
    item = round3.calibration_item(history, scored)

    # Assert
    assert item["rows_scored"] == item["rows_with_all_four_probabilities"] == 6 * 12 * 4
    assert item["largest_gap_between_chained_and_system_forecast"] == 0.0
    assert item["coverage"]["years_left_raw"] == [2001, 2002, 2003]
    assert set(item["brier"]) == {"raw", "calibrated", "usual", "class_frequency"}
    assert item["brier"]["usual"] == pytest.approx(((0.4 - scored["y_season"]) ** 2).mean())
    assert item["skill"]["raw_against_usual"] == pytest.approx(1 - item["brier"]["raw"] / item["brier"]["usual"])
    for entry in item["brier_differences"]:                      # yearly Briers weighted by rows give the pooled Brier
        assert entry[entry["a"] + "_mean"] == pytest.approx(item["brier"][entry["a"].replace(" ", "_")])
    assert sum(row["n"] for row in item["reliability"]["raw"]) == item["rows_scored"]
    assert item["cost_at_threshold"]["raw_total"] == tally_cost(scored["y_season"], scored["p_season"] >= 0.25)
    assert json.loads(json.dumps(item)) == item


def test_round3_header_says_what_the_results_were_computed_against():
    # Arrange / Act
    top = round3.header({"frozen": {"manifest_sha256": "abc"}})

    # Assert
    assert top["added"] is True and top["computed_against_manifest_sha256"] == "abc"
    assert top["score_through"] == SCORE_THROUGH and "Evaluation round 3" in top["declared_in"]
    assert (top["draws"], top["seed"]) == (10000, 0) and "git_commit" in top


# ---------------------------------------------------------------------------------------------
# The freeze (section 3.0): manifest, cut-off, frozen files, and predict() leaving them alone
# ---------------------------------------------------------------------------------------------
def test_scored_keys_of_metrics_equal_the_frozen_file():
    # Arrange
    metrics = json.loads(METRICS.read_text())
    frozen = json.loads((FROZEN / "metrics.json").read_text())

    # Act / Assert: every frozen key is in metrics.json with the same value. The one exception
    # is the reservoir readings' dates, a live piece inside a scored key.
    for key, value in frozen.items():
        if key == "reservoir":
            without_dates = lambda block: {k: v for k, v in block.items() if k != "systems"}
            assert without_dates(metrics[key]) == without_dates(value)
        else:
            assert metrics[key] == value, f"metrics.json differs from the frozen file in '{key}'"
    # and metrics.json adds nothing but the live keys
    assert set(metrics) - set(frozen) == set(export.LIVE_KEYS)
    assert not set(export.LIVE_KEYS) & set(frozen)
    assert frozen["is_final"] is True and frozen["frozen"]["score_through"] == SCORE_THROUGH


def test_handoff_tables_are_byte_identical_to_the_frozen_copies():
    for path in (PREDICTIONS, OUTLOOK):
        assert path.read_bytes() == (FROZEN / path.name).read_bytes(), f"{path.name} is not the frozen copy"


def test_raw_inputs_match_the_manifest_the_frozen_results_name():
    # Arrange / Act
    problems = check_manifest()
    frozen = json.loads((FROZEN / "metrics.json").read_text())

    # Assert
    assert problems == []
    assert frozen["frozen"]["manifest_sha256"] == sha256_of(export.MANIFEST)


def test_manifest_names_a_changed_a_missing_and_a_new_file(tmp_path):
    # Arrange: a small made-up tree (the real data/raw is never touched)
    (tmp_path / "data" / "raw" / "lakes").mkdir(parents=True)
    (tmp_path / "notebooks").mkdir()
    (tmp_path / "data" / "raw" / "drought.json").write_text("0123450")
    (tmp_path / "data" / "raw" / "lakes" / "one.csv").write_text("date,storage\n2026-01-01,5\n")
    (tmp_path / "notebooks" / "oni.txt").write_text("1998 2.22\n")
    (tmp_path / "notebooks" / "not_an_input.py").write_text("print(1)\n")

    # Act
    manifest = build_manifest(tmp_path)
    clean = check_manifest(tmp_path)
    (tmp_path / "data" / "raw" / "drought.json").write_text("0123451")           # one byte changed
    (tmp_path / "data" / "raw" / "lakes" / "one.csv").unlink()
    (tmp_path / "data" / "raw" / "lakes" / "two.csv").write_text("date,storage\n")
    after = check_manifest(tmp_path)

    # Assert
    assert sorted(manifest["files"]) == ["data/raw/drought.json", "data/raw/lakes/one.csv", "notebooks/oni.txt"]
    assert manifest["score_through"] == SCORE_THROUGH and clean == []
    assert after == ["data/raw/drought.json (changed)", "data/raw/lakes/one.csv (missing)",
                     "data/raw/lakes/two.csv (new)"]


def test_a_missing_manifest_is_a_problem_not_a_pass(tmp_path):
    assert check_manifest(tmp_path) == ["data/manifest.json (missing)"]


def test_panel_cut_off_drops_later_weeks_and_every_answer_that_would_cross_it(panel):
    # Arrange: a cut-off 74 weeks before the last week in the file
    cut_off = panel["date"].max() - pd.Timedelta(weeks=74)

    # Act
    cut = build_panel(score_through=str(cut_off.date()))

    # Assert: no later row, and no answer whose window ends after the cut-off
    assert cut["date"].max() == cut_off
    for label, weeks in (("y", ALERT_WEEKS), ("y_season", SEASON_WEEKS), ("y_weeks", YEAR_WEEKS)):
        known = cut[cut[label].notna()]
        assert (known["date"] + pd.Timedelta(weeks=weeks)).max() == cut_off
        # the answers that are known are the same ones the full panel has
        both = known.merge(panel[["fips", "date", label]], on=["fips", "date"], suffixes=("", "_full"))
        assert len(both) == len(known) and (both[label] == both[label + "_full"]).all()
        # and the full panel knows answers the cut panel must not
        full_known = panel[panel[label].notna() & (panel["date"] <= cut_off)]
        assert len(full_known) > len(known)


def test_panel_with_the_cut_off_at_the_last_week_is_the_default_panel(panel):
    # Arrange / Act
    same = build_panel(score_through=str(panel["date"].max().date()))

    # Assert
    pd.testing.assert_frame_equal(same, panel)


def stand_in_for_the_heavy_steps(monkeypatch, root):
    """Point export.py's paths at a temporary folder and replace its slow steps with tiny ones,
    so predict() can run in a test. The real frozen files are copied in as its input."""
    frozen = root / "reports" / "frozen" / "v1"
    frozen.mkdir(parents=True)
    for path in FROZEN.iterdir():
        (frozen / path.name).write_bytes(path.read_bytes())
    for name, path in {"ROOT": root, "FROZEN": frozen, "LIVE": root / "reports" / "live",
                       "METRICS": root / "reports" / "metrics.json", "PROCESSED": root / "data" / "processed",
                       "LATEST": root / "data" / "processed" / "latest.parquet",
                       "PREDICTIONS": root / "data" / "processed" / "predictions.parquet",
                       "OUTLOOK": root / "data" / "processed" / "outlook.parquet"}.items():
        monkeypatch.setattr(export, name, path)
    week = pd.DataFrame({"date": pd.to_datetime(["2027-01-05"]), "fips": ["48061"], "river": ["Rio Grande"]})
    monkeypatch.setattr(export, "build_panel", lambda: week)
    monkeypatch.setattr(export, "alert_v2", lambda panel: (None, None))
    monkeypatch.setattr(export, "latest_table", lambda panel, threshold: week.copy())
    monkeypatch.setattr(export, "add_map_fields", lambda now, panel, error: now)
    monkeypatch.setattr(export, "add_v2_alarm", lambda table, alarm: table)
    monkeypatch.setattr(export, "finish", lambda table, columns, sort_by: table)
    monkeypatch.setattr(export, "live_metrics", lambda panel, latest: {
        "generated_at": "2027-01-07T00:00:00+00:00", "latest_week": "2027-01-05",
        "reservoir_systems": [{"name": "made up"}], "canals": {"total_km": 1},
        "canal_priority": {"levels": []}, "districts": {"n_districts": 0}})
    return frozen


def test_predict_leaves_every_frozen_file_byte_identical(tmp_path, monkeypatch):
    # Arrange
    frozen = stand_in_for_the_heavy_steps(monkeypatch, tmp_path)
    before = {path.name: sha256_of(path) for path in frozen.iterdir()}
    real_metrics_before = sha256_of(METRICS)

    # Act
    export.predict()

    # Assert: the frozen folder is untouched, and so is the real tree
    assert {path.name: sha256_of(path) for path in frozen.iterdir()} == before
    assert sha256_of(METRICS) == real_metrics_before
    # the handoff tables are copies of the frozen ones
    for name in ("predictions.parquet", "outlook.parquet"):
        assert (tmp_path / "data" / "processed" / name).read_bytes() == (frozen / name).read_bytes()
    # metrics.json is the frozen file plus the live keys, each in its old place
    merged = json.loads((tmp_path / "reports" / "metrics.json").read_text())
    frozen_metrics = json.loads((frozen / "metrics.json").read_text())
    assert list(merged)[:3] == ["contract_version", "generated_at", "is_final"]
    assert list(merged)[12:14] == ["test_years", "latest_week"]
    assert list(merged)[-7:] == ["trigger", "reservoir", "losses", "canals", "canal_priority", "v2", "districts"]
    assert merged["latest_week"] == "2027-01-05" and merged["reservoir"]["systems"] == [{"name": "made up"}]
    assert merged["headline"] == frozen_metrics["headline"] and merged["limits"] == frozen_metrics["limits"]
    live = json.loads((tmp_path / "reports" / "live" / "latest.json").read_text())
    assert set(export.LIVE_KEYS) <= set(live)


def test_predict_refuses_to_run_before_anything_was_scored(tmp_path, monkeypatch):
    # Arrange: paths in an empty folder, so there is no frozen file
    monkeypatch.setattr(export, "ROOT", tmp_path)
    monkeypatch.setattr(export, "FROZEN", tmp_path / "reports" / "frozen" / "v1")

    # Act / Assert
    with pytest.raises(RuntimeError, match="evaluate"):
        export.predict()


def test_evaluate_refuses_to_score_when_a_raw_input_changed(monkeypatch):
    # Arrange: the manifest check reports a changed file; nothing after it may run
    monkeypatch.setattr(export, "check_manifest", lambda: ["data/raw/usdm-counties.json (changed)"])
    monkeypatch.setattr(export, "run_alert", lambda **kwargs: pytest.fail("evaluate() went on to score"))

    # Act / Assert
    with pytest.raises(RuntimeError, match="usdm-counties.json"):
        export.evaluate(force=True)


def test_evaluate_refuses_to_replace_frozen_results_unless_forced(tmp_path, monkeypatch):
    # Arrange: a frozen metrics file already exists (in a temporary folder)
    frozen = tmp_path / "reports" / "frozen" / "v1"
    frozen.mkdir(parents=True)
    (frozen / "metrics.json").write_text("{}")
    monkeypatch.setattr(export, "ROOT", tmp_path)
    monkeypatch.setattr(export, "FROZEN", frozen)
    monkeypatch.setattr(export, "check_manifest", lambda: ["stopped here on purpose"])
    monkeypatch.setattr(export, "run_alert", lambda **kwargs: pytest.fail("evaluate() went on to score"))

    # Act / Assert: without the flag it stops at once and names the flag; with it, it gets as far
    # as the manifest check
    with pytest.raises(RuntimeError, match="already exists.*--force"):
        export.evaluate()
    with pytest.raises(RuntimeError, match="stopped here on purpose"):
        export.evaluate(force=True)
    assert (frozen / "metrics.json").read_text() == "{}"


# ---------------------------------------------------------------------------------------------
# Snapshot and live data, and guards on the manual writers (package G)
# ---------------------------------------------------------------------------------------------
def one_more_week(usdm_text):
    """A Drought Monitor file with one extra week (class 0 everywhere), as a download would bring."""
    usdm = json.loads(usdm_text)
    usdm["weeks"] += 1
    usdm["series"] = [series + "0" for series in usdm["series"]]
    return json.dumps(usdm)


def test_a_download_goes_to_the_live_folder_and_leaves_the_snapshot_alone(tmp_path, monkeypatch):
    # Arrange: the "download" is the saved file with one more week; data/live is a temporary folder
    monkeypatch.setattr(config, "LIVE_DATA", tmp_path)
    snapshot_before = sha256_of(config.USDM_JSON)
    newer = one_more_week(config.USDM_JSON.read_text())
    monkeypatch.setattr(refresh, "fetch", lambda url: newer)

    # Act: two refreshes, as on two days with the same file upstream
    with config.live_data():
        first = refresh.refresh_drought()
        second = refresh.refresh_drought()

    # Assert: the newer file is in the live folder; the snapshot and the manifest check are untouched,
    # so the test that guards the frozen results still passes after a download
    assert first == ("2026-11-17", True) and second == ("2026-11-17", False)
    assert (tmp_path / "usdm-counties.json").read_text() == newer
    assert sha256_of(config.USDM_JSON) == snapshot_before and check_manifest() == []


def test_only_code_inside_live_data_sees_a_newer_download(tmp_path, monkeypatch):
    # Arrange: a newer Drought Monitor file in the live folder
    monkeypatch.setattr(config, "LIVE_DATA", tmp_path)
    (tmp_path / "usdm-counties.json").write_text(one_more_week(config.USDM_JSON.read_text()))

    # Act
    scored_view = load_usdm()["dates"][-1]
    with config.live_data():
        forecast_view = load_usdm()["dates"][-1]
    afterwards = load_usdm()["dates"][-1]

    # Assert: scoring code reads the snapshot before and after; the forecast reads one week more
    assert scored_view == afterwards == pd.Timestamp(SCORE_THROUGH)
    assert forecast_view == pd.Timestamp(SCORE_THROUGH) + pd.Timedelta(weeks=1)
    assert config.raw_path(config.USDM_JSON) == config.USDM_JSON


def test_live_copies_keep_their_names_and_the_switch_always_goes_back(tmp_path, monkeypatch):
    # Arrange
    monkeypatch.setattr(config, "LIVE_DATA", tmp_path)

    # Act / Assert: where each refreshed file goes
    assert config.live_copy(config.ONI_TXT) == tmp_path / "oni.txt"
    assert config.live_copy(config.RESERVOIR_DIR / "falcon.csv") == tmp_path / "reservoirs" / "falcon.csv"
    # a file with no live copy is read from the snapshot even inside the block
    with config.live_data():
        assert config.raw_path(config.ONI_TXT) == config.ONI_TXT
        (tmp_path / "oni.txt").write_text("1998 2.22\n")
        assert config.raw_path(config.ONI_TXT) == tmp_path / "oni.txt"
    assert config.raw_path(config.ONI_TXT) == config.ONI_TXT
    # an error inside the block still switches it off
    with pytest.raises(ZeroDivisionError):
        with config.live_data():
            1 / 0
    assert config.raw_path(config.ONI_TXT) == config.ONI_TXT


def test_predict_reads_live_data_and_nothing_that_scores_does(tmp_path, monkeypatch):
    # Arrange: predict() with stand-ins; the panel builder notes whether the live switch was on
    stand_in_for_the_heavy_steps(monkeypatch, tmp_path)
    seen = []
    week = pd.DataFrame({"date": pd.to_datetime(["2027-01-05"]), "fips": ["48061"], "river": ["Rio Grande"]})
    monkeypatch.setattr(export, "build_panel", lambda: (seen.append(config._LIVE["on"]), week)[1])

    # Act
    export.predict()

    # Assert: on while predicting, off again afterwards
    assert seen == [True] and config._LIVE["on"] is False
    # the scoring step and the scoring scripts never turn it on
    assert "live_data" not in inspect.getsource(export.evaluate)
    for module in (v2, robustness, round3, alert_module):
        assert "live_data" not in inspect.getsource(module)


def test_evaluate_scores_only_up_to_the_cut_off(monkeypatch):
    # Arrange: stop evaluate() at its first scoring call and keep what it was asked for
    asked = {}
    class Stop(Exception):
        pass
    def fake_run_alert(*args, **kwargs):
        asked["args"], asked["kwargs"] = args, kwargs
        raise Stop
    monkeypatch.setattr(export, "check_manifest", lambda: [])
    monkeypatch.setattr(export, "run_alert", fake_run_alert)

    # Act
    with pytest.raises(Stop):
        export.evaluate(force=True)

    # Assert
    assert asked == {"args": (), "kwargs": {"score_through": SCORE_THROUGH}}


def test_run_alert_hands_the_cut_off_to_the_panel_builder(monkeypatch):
    # Arrange
    asked = []
    class Stop(Exception):
        pass
    def fake_build_panel(*args, **kwargs):
        asked.append((args, kwargs))
        raise Stop
    monkeypatch.setattr(alert_module, "build_panel", fake_build_panel)

    # Act
    with pytest.raises(Stop):
        alert_module.run_alert(score_through="2020-01-07")
    with pytest.raises(Stop):
        alert_module.run_alert()

    # Assert: the cut-off reaches build_panel, and the default is still "no cut-off"
    assert asked == [((50, "2020-01-07"), {}), ((50, None), {})]
    # the other writers of scored numbers build their panel with the cut-off too
    for module in (v2, robustness, round3):
        assert "score_through=SCORE_THROUGH" in inspect.getsource(module)
    pre2020 = (config.ROOT / "app" / "forecast_pre2020.py").read_text()
    assert "run_alert(score_through=SCORE_THROUGH)" in pre2020 and "guard_scored_writer(OUT" in pre2020


def test_manual_writers_refuse_to_replace_a_scored_file_after_the_freeze(tmp_path):
    # Arrange: a frozen metrics file and an existing output, both in a temporary folder
    frozen = tmp_path / "metrics.json"
    output = tmp_path / "v2.json"
    frozen.write_text("{}")
    output.write_text("old")

    # Act / Assert: refused without the flag, allowed with it
    with pytest.raises(RuntimeError, match="v2.json already exists.*--force"):
        guard_scored_writer(output, frozen_metrics=frozen)
    guard_scored_writer(output, force=True, frozen_metrics=frozen)
    # a first run (no output yet) and a run before any freeze are allowed
    guard_scored_writer(tmp_path / "new.json", frozen_metrics=frozen)
    guard_scored_writer(output, frozen_metrics=tmp_path / "no_freeze_yet.json")
    assert output.read_text() == "old"
    # and each of the three scripts calls the guard before it does anything else
    for module in (v2, robustness):
        assert "guard_scored_writer(" in inspect.getsource(module)


def test_manual_writers_refuse_when_a_raw_input_changed(tmp_path, monkeypatch):
    # Arrange: the manifest check reports a changed file; even --force must not get past it
    import farmdrought.manifest as manifest_module
    monkeypatch.setattr(manifest_module, "check_manifest", lambda root=None: ["data/raw/usdm-counties.json (changed)"])

    # Act / Assert
    with pytest.raises(RuntimeError, match="usdm-counties.json"):
        guard_scored_writer(tmp_path / "v2.json", force=True, frozen_metrics=tmp_path / "metrics.json")


def test_machine_note_is_built_from_the_numbers_it_is_given():
    # Arrange: made-up results in the shape evaluate() holds them
    alert = {"headline": {"system_cost": 1912}, "per_river": [{"all_rivers_cost": 1760}]}
    season = {"focus": {"system_cost": 2324, "persistence_cost": 3133, "d1_rule_cost": 2382, "usual_cost": 3871,
                        "always_warn_cost": 3403, "never_warn_cost": 9786}}
    year = {"focus": {"mae_system": 14.0}}
    checks = {"seed_check": {"runs": [{}] * 10, "summary": {"season_cost": {"lowest": 2324, "highest": 2453}}}}

    # Act
    note = export.machine_note(alert, season, year, checks)
    without_checks = export.machine_note(alert, season, year, None)

    # Assert: 2324 against the runner's 2328 is 4; 1760 against 1883 is 123; 2382 - 2324 is 58
    assert "moved by 0, 4 and 0" in note and "moved by 123 (1760 here, 1883 there)" in note
    assert "ranges from 2324 to 2453 across 10 random seeds, against a margin of 58" in note
    assert note.endswith("the random seed, more than the computer, is why a margin of that size is not a result.")
    assert "random seeds" not in without_checks and "moved by 123" in without_checks


# ---------------------------------------------------------------------------------------------
# The physical model (package H)
# ---------------------------------------------------------------------------------------------
def test_bed_layer_takes_the_main_soil_and_the_layer_at_one_metre_with_its_permeability():
    # Arrange: map unit 1 has two soils; the main one (70%) has three layers, 0-30, 30-120, 120-200 cm.
    # Map unit 2 has one shallow soil that ends at 60 cm. Values arrive as text, as the service sends them.
    layers = pd.DataFrame([
        {"mukey": "1", "cokey": "a", "comppct_r": "70", "hzdept_r": "0", "hzdepb_r": "30", "texcl": "Loam", "ksat_r": "9"},
        {"mukey": "1", "cokey": "a", "comppct_r": "70", "hzdept_r": "30", "hzdepb_r": "120", "texcl": "Clay", "ksat_r": "0.9"},
        {"mukey": "1", "cokey": "a", "comppct_r": "70", "hzdept_r": "120", "hzdepb_r": "200", "texcl": "Sand", "ksat_r": "90"},
        {"mukey": "1", "cokey": "b", "comppct_r": "30", "hzdept_r": "0", "hzdepb_r": "200", "texcl": "Sand", "ksat_r": "92"},
        {"mukey": "2", "cokey": "c", "comppct_r": "100", "hzdept_r": "0", "hzdepb_r": "20", "texcl": "Loam", "ksat_r": "9"},
        {"mukey": "2", "cokey": "c", "comppct_r": "100", "hzdept_r": "20", "hzdepb_r": "60", "texcl": "Silt loam", "ksat_r": "4"},
        {"mukey": "2", "cokey": "c", "comppct_r": "100", "hzdept_r": "60", "hzdepb_r": "80", "texcl": None, "ksat_r": "1"},
    ])

    # Act
    picked = bed_layer(layers).set_index("mukey")

    # Assert: unit 1 -> the 30-120 cm layer of soil a; unit 2 -> its deepest layer that has a texture
    assert picked.loc["1", ["cokey", "texcl", "ksat_r"]].tolist() == ["a", "Clay", "0.9"]
    assert picked.loc["2", ["cokey", "texcl", "ksat_r"]].tolist() == ["c", "Silt loam", "4"]
    assert len(picked) == 2


def test_manifest_ignores_files_that_are_not_scored_inputs(tmp_path):
    # Arrange: a small tree with a manifest, then the round-3 permeability file appears
    (tmp_path / "data" / "raw" / "canals").mkdir(parents=True)
    (tmp_path / "data" / "raw" / "canals" / "canal_soil.csv").write_text("id,mukey,soil\n")
    build_manifest(tmp_path)

    # Act
    (tmp_path / "data" / "raw" / "canals" / "canal_ksat.csv").write_text("id,mukey,ksat_typ\n")
    (tmp_path / "data" / "raw" / "canals" / "something_else.csv").write_text("x\n")

    # Assert: the listed file is ignored; any other new file is still reported
    assert check_manifest(tmp_path) == ["data/raw/canals/something_else.csv (new)"]
    assert "data/raw/canals/canal_ksat.csv" not in build_manifest(tmp_path)["files"]


def test_seepage_rate_converts_one_micrometre_per_second_to_2_1205_gallons():
    # Arrange: by hand, 1 micrometre per second = 0.000001 m x 86,400 s = 0.0864 m per day
    feet_per_day = 0.0864 / 0.3048
    gallons_per_cubic_foot = 7.48052

    # Act
    rate = seepage_rate(1.0, None)

    # Assert
    assert rate == 2.1205
    assert rate == pytest.approx(feet_per_day * gallons_per_cubic_foot, abs=5e-5)
    assert seepage_rate(1.0, None, c=0.5) == pytest.approx(1.06025)       # the calibration factor scales it


def test_water_table_factor_at_the_depths_that_define_it():
    # Act / Assert: no effect when deep or unknown, a straight line between 300 and 100 cm, 0.1 below
    assert water_table_factor(400) == 1.0
    assert water_table_factor(300) == 1.0
    assert water_table_factor(200) == pytest.approx(0.55)                # halfway between 1 and 0.1
    assert water_table_factor(100) == pytest.approx(0.1)
    assert water_table_factor(50) == 0.1
    assert water_table_factor(0) == 0.1
    assert water_table_factor(None) == 1.0 and water_table_factor(float("nan")) == 1.0
    # and the rate carries it
    assert seepage_rate(10.0, 200) == pytest.approx(10 * 2.1205 * 0.55)
    assert seepage_rate(10.0, 50) == pytest.approx(10 * 2.1205 * 0.1)


def test_seepage_rate_rises_with_permeability_and_is_missing_without_it():
    # Arrange: permeabilities from the tightest clay to the coarsest sand in the canal file
    permeabilities = [0.21, 1.0, 9.0, 28.0, 141.14, 423.07]

    # Act
    deep = [seepage_rate(k, None) for k in permeabilities]
    shallow = [seepage_rate(k, 120) for k in permeabilities]

    # Assert: strictly rising at any water-table depth, and a shallow table always lowers it
    assert all(a < b for a, b in zip(deep, deep[1:])) and all(a < b for a, b in zip(shallow, shallow[1:]))
    assert all(s < d for s, d in zip(shallow, deep))
    assert np.isnan(seepage_rate(None, 200)) and np.isnan(seepage_rate(float("nan"), None))
    assert seepage_rate(0.0, None) == 0.0
