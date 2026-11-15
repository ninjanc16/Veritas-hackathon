"""Checks for the canal-action pivot: the reservoir inputs and the trigger scoring."""
import json

import numpy as np
import pandas as pd

from farmdrought.canals import county_polygons, inside_county, inside_ring
from farmdrought.config import CANALS_CSV, CANALS_GEOJSON, LATEST, LEAKY_SOIL_RATE, SEASON_THRESHOLD
from farmdrought.leaks import rate_canals
from farmdrought.reservoirs import FEATURES_R, add_reservoir_features, load_reservoirs, reservoir_features
from farmdrought.trigger import score, value


def test_trigger_counts_on_a_hand_made_table():
    # 10 decisions. A drought season followed the first 4.
    y = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
    fires = [True, True, True, False, True, True, False, False, False, False]
    result = score("rule", y, fires)
    assert result["fires"] == 5 and result["caught"] == 3 and result["missed"] == 1 and result["false_alarms"] == 2
    assert result["recall"] == 0.75 and result["precision"] == 0.6
    # value = (caught - cost ratio x fires) / rows = (3 - 0.25 x 5) / 10
    assert value(y, fires, 0.25) == 0.175
    assert value(y, [False] * 10, 0.25) == 0   # never sealing is worth exactly 0


def test_reservoir_inputs_do_not_use_the_future():
    """LEAKAGE CHECK: rewriting every day AFTER the issue date must not change any input."""
    pct = load_reservoirs()["Elephant Butte"]
    dates = pd.DatetimeIndex(["2012-03-06", "2018-01-02"])
    before = reservoir_features(pct, dates)
    changed = pct.copy()
    changed[changed.index > dates.max()] = 99.0   # a made-up future: the lake is suddenly full
    after = reservoir_features(changed, dates)
    pd.testing.assert_frame_equal(before, after)


def test_reservoir_inputs_on_real_rows(panel):
    rows = panel[panel["date"] == panel["date"].max()]
    table = add_reservoir_features(rows)
    assert not table[FEATURES_R].isna().any().any()
    with_res = table[table["has_res"] == 1]
    assert len(with_res) == 14 and set(with_res["river"]) == {"Rio Grande"}
    assert with_res["res_pct"].between(0, 100).all() and with_res["res_pctile"].between(0, 1).all()
    # Counties with no reservoir get -1 in all four inputs
    assert (table.loc[table["has_res"] == 0, FEATURES_R[:4]] == -1).all().all()


def test_point_in_shape_on_a_hand_made_square():
    square = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    hole = [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]
    assert inside_ring(5, 5, square) and not inside_ring(11, 5, square) and not inside_ring(5, -1, square)
    assert inside_county(1, 1, [[square, hole]])       # inside the square, outside the hole
    assert not inside_county(5, 5, [[square, hole]])   # inside the hole


def test_every_canal_segment_is_inside_the_county_it_was_given():
    table = pd.read_csv(CANALS_CSV, dtype={"fips": str})
    assert table["id"].is_unique and (table["length_km"] >= 0).all()   # no segment counted twice
    shapes = county_polygons(set(table["fips"]))
    assert all(inside_county(row.lon, row.lat, shapes[row.fips]) for row in table.itertuples())
    # The map file holds the same segments as the table
    with open(CANALS_GEOJSON) as f:
        assert len(json.load(f)["features"]) == len(table)


def test_canal_levels_follow_the_rule():
    """Inspect first = forecast warns AND leaky soil. Check every segment against the rule."""
    canals = rate_canals(pd.read_parquet(LATEST))
    known = canals[~canals["level"].isin(["Unknown soil", "Drain"])]
    warns, leaky = known["p_season"] >= SEASON_THRESHOLD, known["seepage_rate"] >= LEAKY_SOIL_RATE
    assert (known.loc[warns & leaky, "level"] == "Inspect first").all()
    assert (known.loc[warns ^ leaky, "level"] == "Watch").all()      # exactly one of the two
    assert (known.loc[~warns & ~leaky, "level"] == "Low").all()
    assert canals.loc[canals["level"] == "Unknown soil", "seepage_rate"].isna().all()
    assert (canals.loc[canals["level"].isin(["Unknown soil", "Drain"]), "score"] == 0).all()


# ================================ districts and the sealant plan ================================

def toy_canals():
    """Four canals inside a district and one outside. Each is 1 km long."""
    return pd.DataFrame({
        "id": ["a", "b", "c", "d", "e"], "length_km": 1.0,
        "district": ["D", "D", "D", "D", ""],
        "score": [5.0, 9.0, 0.0, 2.0, 99.0],          # c is a drain or unknown soil (score 0)
        "seepage_rate": [7.48, 11.22, None, 2.99, 11.22]})


def test_sealant_goes_to_the_highest_score_first_and_stays_inside_the_budget():
    from farmdrought.config import FEET_PER_KM, SEALANT_USD_PER_SQFT, WETTED_WIDTH_FT
    from farmdrought.districts import sealant_plan
    one_km = FEET_PER_KM * WETTED_WIDTH_FT * SEALANT_USD_PER_SQFT   # cost of sealing 1 km
    plan = sealant_plan(toy_canals(), budget=2.5 * one_km).set_index("id")
    # ranked by score: b (9), a (5), d (2). The budget pays for two of them.
    assert list(plan.loc[["b", "a", "d"], "seal_rank"]) == [1, 2, 3]
    assert list(plan.loc[["b", "a", "d"], "funded"]) == [True, True, False]
    assert plan.loc[plan["funded"], "seal_usd"].sum() <= 2.5 * one_km
    # a canal with score 0, and a canal outside every district, are never ranked or funded
    assert plan.loc[["c", "e"], "seal_rank"].isna().all() and not plan.loc[["c", "e"], "funded"].any()


def test_canal_is_given_the_district_it_lies_inside():
    from farmdrought.districts import assign_districts
    square = [[[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]]            # one polygon, one ring
    districts = {"Square District": ({}, square)}
    canals = pd.DataFrame({"fips": ["48061", "48061", "35013"], "lon": [1.0, 5.0, 1.0], "lat": [1.0, 5.0, 1.0]})
    # inside the square; outside it; inside but not a Texas county (boundaries are Texas only)
    assert assign_districts(canals, districts) == ["Square District", "", ""]


def test_districts_block_adds_up():
    from farmdrought.config import DISTRICTS_GEOJSON, METRICS
    with open(METRICS) as f:
        block = json.load(f)["districts"]
    rows = block["districts"]
    assert len(rows) == block["n_districts"] > 0
    assert sum(r["sealant_usd"] for r in rows) <= block["budget_usd"]          # never over budget
    assert abs(sum(r["sealant_usd"] for r in rows) - block["spent_usd"]) <= len(rows)  # rounding only
    assert all(r["risk"] in {"Low", "Watch", "Warning"} and 0 <= r["p_season"] <= 1 for r in rows)
    assert all(r["sealed_km"] <= r["treatable_km"] <= r["canal_km"] for r in rows)
    with open(DISTRICTS_GEOJSON) as f:
        assert len(json.load(f)["features"]) == len(rows)                      # one shape per listed district
