"""
costs.py - the lining-cost arithmetic, moved here from app/canal.py.

NONE of this is AI. This file only does simple multiplication and division on published
figures. Every function is pure: numbers in, numbers out, nothing read or written. Results are
ESTIMATES from published figures, not predictions and not tested results.
"""

LINING_LIFE_YEARS = 50      # a concrete lining is assumed to last 50 years (spreads its cost)


def wetted_area_sqft(miles, width_ft):
    """Area of canal bed and banks that water touches = miles x 5,280 ft x wetted width."""
    return miles * 5280 * width_ft


def lining_cost_per_af_range(miles, width_ft, seepage_af, costs):
    """(low, high) dollars per acre-foot for concrete lining, spread over its 50-year life.
    Assumes lining stops all seepage (its best case)."""
    if seepage_af <= 0:
        return None, None
    area = wetted_area_sqft(miles, width_ft)
    water_over_life = seepage_af * LINING_LIFE_YEARS
    return (area * costs["lining_usd_per_sqft_low"] / water_over_life,
            area * costs["lining_usd_per_sqft_high"] / water_over_life)
