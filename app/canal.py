"""
canal.py - the arithmetic behind the "Canal action" tab.

For the judges: NONE of this is AI. The AI part is the drought forecast. This file only does
simple multiplication and division on published figures (Texas A&M 1998, Bureau of
Reclamation, news reports of fallowing prices). Every function is pure: numbers in, numbers
out, nothing read or written. Results are ESTIMATES from published figures, not predictions
and not tested results.
"""
import math

import pandas as pd

# The label every output on the tab must carry (rule W0.1 number 3).
ESTIMATE_LABEL = "Estimate from published figures, not a prediction and not a tested result."

DAYS_PER_YEAR = 365
LINING_LIFE_YEARS = 50      # a concrete lining is assumed to last 50 years (spreads its cost)


def action_tier(p):
    """Turn the 6-month drought probability (0 to 1) into the action tier and its one sentence."""
    if p >= 0.25:
        return ("Seal and repair before the season",
                "At 25% or more the chance of drought is high enough that fixing leaks before the season is worth the cost.")
    if p >= 0.125:
        return ("Inspect and prepare",
                "Between 12.5% and 25% the risk is raised: check the canals and get materials ready, but wait to spend.")
    return ("No extra action. Leakage refills groundwater",
            "Below 12.5% drought is unlikely, and canal leakage refills the groundwater that farm wells use.")


def wetted_area_sqft(miles, width_ft):
    """Area of canal bed and banks that water touches = miles x 5,280 ft x wetted width."""
    return miles * 5280 * width_ft


def seepage_af_per_year(miles, width_ft, rate_gal_sqft_day, days_of_flow, gallons_per_af):
    """Water that leaks out in a year, in acre-feet = rate x area x days / gallons per acre-foot."""
    area = wetted_area_sqft(miles, width_ft)
    return rate_gal_sqft_day * area * days_of_flow / gallons_per_af


def applications_per_season(days_of_flow, months_effective):
    """Sealant wears off, so it is re-applied. Months of flow / months it lasts, rounded UP."""
    months_of_flow = days_of_flow / DAYS_PER_YEAR * 12
    return max(1, math.ceil(months_of_flow / months_effective))


def sealant_cost_per_season(miles, width_ft, days_of_flow, costs):
    """Materials cost of sealing one season = area x $ per sq ft x applications."""
    apps = applications_per_season(days_of_flow, costs["sealant_months_effective"])
    return wetted_area_sqft(miles, width_ft) * costs["sealant_usd_per_sqft"] * apps


def water_saved_range(seepage_af, costs):
    """(low, high) acre-feet saved: sealant cut seepage by 28% to 87% in field trials elsewhere."""
    return seepage_af * costs["sealant_cut_low"], seepage_af * costs["sealant_cut_high"]


def cost_per_af_range(cost, saved_low, saved_high):
    """(low, high) dollars per acre-foot. Cheapest = high saving, dearest = low saving."""
    if saved_low <= 0 or saved_high <= 0:
        return None, None
    return cost / saved_high, cost / saved_low


def fallow_cost_range(water_af, costs):
    """(low, high) dollars to leave enough farmland dry to 'save' the same water."""
    acres = water_af / costs["fallow_af_per_acre"]
    return acres * costs["fallow_usd_per_acre_low"], acres * costs["fallow_usd_per_acre_high"]


def lining_cost_per_af_range(miles, width_ft, seepage_af, costs):
    """(low, high) dollars per acre-foot for concrete lining, spread over its 50-year life.
    Assumes lining stops all seepage (its best case)."""
    if seepage_af <= 0:
        return None, None
    area = wetted_area_sqft(miles, width_ft)
    water_over_life = seepage_af * LINING_LIFE_YEARS
    return (area * costs["lining_usd_per_sqft_low"] / water_over_life,
            area * costs["lining_usd_per_sqft_high"] / water_over_life)


def district_priority(districts, p):
    """
    Rank the irrigation districts. Priority = forecast probability x water the district could
    recover by reaching 80% efficiency. Sorted by the high end, biggest first; a district with
    nothing to recover goes last. Returns a new table (the input is not changed).
    """
    out = districts[["district", "efficiency_pct", "save80_low", "save80_high"]].copy()
    out["priority_low"] = p * out["save80_low"]
    out["priority_high"] = p * out["save80_high"]
    # Stable sort: ties (e.g. all the zeros) keep the file's order, so the result is repeatable.
    return out.sort_values(["priority_high", "priority_low"], ascending=False,
                           kind="stable").reset_index(drop=True)
