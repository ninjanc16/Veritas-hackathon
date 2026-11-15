"""Tests for the sealant ranking with and without the forecast (districts.py)."""
import pandas as pd

from farmdrought.config import FEET_PER_KM, SEALANT_USD_PER_SQFT, WETTED_WIDTH_FT
from farmdrought.districts import forecast_effect, rank_correlation, sealant_plan

USD_PER_KM = FEET_PER_KM * WETTED_WIDTH_FT * SEALANT_USD_PER_SQFT   # what one kilometre of canal costs to seal


def small_table():
    """Six made-up canals, 1 km each, in two districts.

    District "North" sits in a county with a low drought chance (0.1) and leaky soil.
    District "South" sits in a county with a high chance (0.8) and tighter soil.
    So the forecast pulls money south, and seepage alone pulls it north.
    The last two rows cannot be treated: one has no district, one is a drain (score 0).
    """
    rows = [  # id, district, seepage_rate, p_season, score (0 = a drain or unknown soil)
        ("a", "North", 9.0, 0.1, 0.90), ("b", "North", 7.0, 0.1, 0.70),
        ("c", "South", 4.0, 0.8, 3.20), ("d", "South", 2.0, 0.8, 1.60),
        ("e", "", 9.0, 0.8, 7.20), ("f", "South", 9.0, 0.8, 0.0),
    ]
    table = pd.DataFrame(rows, columns=["id", "district", "seepage_rate", "p_season", "score"])
    table["length_km"] = 1.0
    return table


def test_the_default_plan_is_the_plan_with_the_forecast_and_is_unchanged():
    # Arrange
    canals = small_table()

    # Act: the call as it was before the new argument, and the same call spelled out
    before = sealant_plan(canals, budget=2 * USD_PER_KM + 1)
    spelled = sealant_plan(canals, budget=2 * USD_PER_KM + 1, use_forecast=True)

    # Assert: identical tables; ranked by score, so the two South canals come first and are funded
    pd.testing.assert_frame_equal(before, spelled)
    assert before.set_index("id")["seal_rank"].dropna().to_dict() == {"c": 1, "d": 2, "a": 3, "b": 4}
    assert before.loc[before["funded"], "id"].tolist() == ["c", "d"]
    assert list(before.columns) == ["id", "district", "seepage_rate", "p_season", "score", "length_km", "seal_sqft",
                                    "seal_usd", "seal_rank", "funded", "saved_af_low", "saved_af_high"]


def test_without_the_forecast_the_order_is_by_seepage_rate_alone():
    # Arrange
    canals = small_table()

    # Act
    plan = sealant_plan(canals, budget=2 * USD_PER_KM + 1, use_forecast=False)

    # Assert: the same four canals can be treated, leakiest first, and the money goes north
    ranked = plan[plan["seal_rank"].notna()].sort_values("seal_rank")
    assert ranked["id"].tolist() == ["a", "b", "c", "d"]
    assert ranked["seepage_rate"].is_monotonic_decreasing
    assert plan.loc[plan["funded"], "id"].tolist() == ["a", "b"]
    # the drought chance played no part: changing it changes nothing
    shuffled = canals.assign(p_season=[0.9, 0.0, 0.1, 0.5, 0.2, 0.3])
    assert sealant_plan(shuffled, budget=2 * USD_PER_KM + 1, use_forecast=False)["seal_rank"].equals(plan["seal_rank"])
    # cost, area and water saved do not depend on the order
    with_forecast = sealant_plan(canals, budget=2 * USD_PER_KM + 1)
    for column in ["seal_sqft", "seal_usd", "saved_af_low", "saved_af_high"]:
        assert plan[column].equals(with_forecast[column])


def test_ties_in_seepage_rate_go_to_the_lower_id():
    canals = small_table().assign(seepage_rate=5.0)
    plan = sealant_plan(canals, use_forecast=False)
    assert plan[plan["seal_rank"].notna()].sort_values("seal_rank")["id"].tolist() == ["a", "b", "c", "d"]


def test_forecast_effect_counts_the_km_each_plan_funds_and_the_rank_correlation():
    # Arrange: enough money for two of the four treatable canals
    canals = small_table()

    # Act
    effect = forecast_effect(canals, budget=2 * USD_PER_KM + 1)

    # Assert: with the forecast c and d are funded, without it a and b: nothing in common
    assert effect["overall"] == {"ranked_km": 4.0, "both_km": 0.0, "only_forecast_km": 2.0,
                                 "only_no_forecast_km": 2.0, "rank_correlation": -0.6}
    by_name = {row["district"]: row for row in effect["districts"]}
    assert list(by_name) == ["North", "South"]
    assert by_name["North"]["only_no_forecast_km"] == 2.0 and by_name["North"]["only_forecast_km"] == 0.0
    assert by_name["South"]["only_forecast_km"] == 2.0 and by_name["South"]["only_no_forecast_km"] == 0.0
    # inside one district every canal has the same drought chance, so the two orders agree there
    assert by_name["North"]["rank_correlation"] == 1.0 and by_name["South"]["rank_correlation"] == 1.0
    assert effect["budget_usd"] == 2 * USD_PER_KM + 1


def test_forecast_effect_reports_no_difference_as_zeros():
    # Arrange: one drought chance everywhere, so the forecast cannot change the order
    canals = small_table().assign(p_season=0.5)
    canals["score"] = (canals["seepage_rate"] * 0.5).where(canals["score"] > 0, 0)

    # Act
    overall = forecast_effect(canals, budget=2 * USD_PER_KM + 1)["overall"]

    # Assert
    assert overall == {"ranked_km": 4.0, "both_km": 2.0, "only_forecast_km": 0.0, "only_no_forecast_km": 0.0,
                       "rank_correlation": 1.0}


def test_rank_correlation_is_one_for_the_same_order_and_none_when_there_is_nothing_to_compare():
    assert rank_correlation([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0      # re-ranked from 1 first
    assert rank_correlation([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert rank_correlation([1, 2, 3], [2, 1, 3]) == 0.5                # 1 - 6 x 2 / (3 x 8)
    assert rank_correlation([5], [9]) is None
    assert rank_correlation([], []) is None
