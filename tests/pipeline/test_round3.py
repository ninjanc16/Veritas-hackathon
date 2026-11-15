"""Tests for the round 3 evaluation work (ARCHITECTURE.md section 3). So far: uncertainty.py."""
import json

import numpy as np
import pandas as pd
import pytest

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
