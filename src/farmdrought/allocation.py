"""
allocation.py - the budget-ranking backtest: if only k counties can be funded, who picks better?

ADDED in round 3 (ARCHITECTURE.md section 3.4). It changes no version 1 number, and nothing
here is trained: it only re-scores forecasts that outlook.py already made.

THE DECISION. Each March a fixed budget pays for canal work in k of the Rio Grande counties,
at the same cost each. Which k? Each ranking below puts the counties in order and the top k are
funded. A ranking is scored by the share of its funded counties that then had a drought season
(y_season = 1). HIGHER IS BETTER here.

  Model   : the 6-month forecast p_season, highest first
  Rule A  : today's drought class, highest first, then the longest current D2 streak
  Rule B  : today's drought class, highest first, then the highest 12-week average class
  Random  : what a random pick gets on average, which is the year's base rate
  Oracle  : the best any ranking could do that year (it knows the answers)
Every tie is broken by FIPS code, lowest first.

Only columns known on the issue date decide who is funded: p_season, cls, d2_streak, mean12
and fips. The answer y_season is used only afterwards, to score.

This needs the scored table as run_outlook returns it. The exported outlook.parquet does not
carry d2_streak or mean12.
"""
import pandas as pd

from farmdrought.config import FOCUS_RIVER
from farmdrought.uncertainty import year_block_bootstrap

# name -> (columns to sort by, True where a column is sorted lowest first)
RANKINGS = {
    "model": (["p_season", "fips"], [False, True]),
    "rule_a": (["cls", "d2_streak", "fips"], [False, False, True]),
    "rule_b": (["cls", "mean12", "fips"], [False, False, True]),
}
RULES = ["rule_a", "rule_b"]
NEEDED = ["p_season", "cls", "d2_streak", "mean12", "fips", "y_season"]


def model_minus_rule(model, rule, draws=10000, seed=0):
    """Interval for (model share minus rule share), resampling whole years.

    SIGN: a higher share is better here, so the plain shares are passed to
    year_block_bootstrap with lower_is_better=False. "diff", "lo" and "hi" below are model minus
    rule in plain shares, so ABOVE zero means the model funded more counties that went on to a
    drought season. The two "better" counts are renamed so nobody has to remember which way
    they point. "caveat" must be printed wherever the interval is.

    Every year counts the same (weighted-mean mode with weight 1 per year), so "diff" is the
    difference of the two means over years.
    """
    weights = pd.Series(1.0, index=model.index)
    raw = year_block_bootstrap(model, rule, weights=weights, draws=draws, seed=seed, lower_is_better=False)
    return {
        "diff": raw["diff"], "lo": raw["lo"], "hi": raw["hi"],
        "share_draws_model_better": raw["share_draws_a_better"],
        "years_model_better": raw["years_a_better"],
        "n_years": raw["n_years"], "draws": raw["draws"], "block": raw["block"], "seed": raw["seed"],
        "higher_is_better": True, "caveat": raw["caveat"],
    }


def _block(shares, draws, seed):
    """Means over years, which rule is the better one, and the model-minus-that-rule interval.

    shares : one column per ranking (and random, oracle), one row per year.
    The better rule is decided ONCE, by its mean over all years, never year by year. On an
    exact tie it is rule A.
    """
    means = {name: float(shares[name].mean()) for name in shares}
    better = max(RULES, key=lambda name: means[name])          # max() keeps the first on a tie
    difference = shares["model"] - shares[better]
    return {
        "per_year": {name: [float(v) for v in shares[name]] for name in shares},
        "mean": means,
        "better_rule": better,
        "model_minus_better_rule": {"per_year": [float(v) for v in difference],
                                    "mean": float(difference.mean()),
                                    "interval": model_minus_rule(shares["model"], shares[better], draws, seed)},
    }


def run_allocation(scored, ks=(3, 5, 8, 10, 15), month=3, draws=10000, seed=0):
    """Score the rankings on the Rio Grande outlooks issued in `month`, for each budget k.

    Returns a dict (plain numbers and lists, safe for json.dump). Every per-year list is in the
    order of "years".
      years, n_years, counties_per_year, rows, month, ks
      per_k           : one entry per k with
                          per_year  the share for model, rule_a, rule_b, random and oracle
                          mean      each of those averaged over years
                          funded    the FIPS codes each ranking funded, year by year
                          better_rule and model_minus_better_rule (see _block)
      average_over_k  : the same, after first averaging each year's shares over the ks
                        (no "funded" list)
    A share is between 0 and 1 and HIGHER IS BETTER. See model_minus_rule for how the interval's
    sign is handled.
    """
    focus = scored[scored["river"] == FOCUS_RIVER]
    rows = focus[focus["date"].dt.month == month]
    if rows[NEEDED].isna().any().any():
        raise ValueError("a ranking column or the answer is missing in some rows")
    year_of = rows["date"].dt.year
    if pd.MultiIndex.from_arrays([rows["fips"], year_of]).has_duplicates:
        raise ValueError("a county appears more than once in one year")
    years = sorted(int(y) for y in year_of.unique())
    counties = {year: int((year_of == year).sum()) for year in years}
    if not years:
        raise ValueError(f"no {FOCUS_RIVER} rows were issued in month {month}")
    too_big = [k for k in ks if k > min(counties.values())]
    if too_big:
        raise ValueError(f"cannot fund k = {too_big} counties: the smallest year has {min(counties.values())}")

    # The funding order of each ranking, worked out once per year from issue-date columns only.
    order = {name: {year: rows[year_of == year].sort_values(columns, ascending=ascending, kind="stable")
                    for year in years}
             for name, (columns, ascending) in RANKINGS.items()}

    per_k, all_shares = [], []
    for k in ks:
        shares = pd.DataFrame(index=years, columns=[*RANKINGS, "random", "oracle"], dtype=float)
        funded = {name: [] for name in RANKINGS}
        for year in years:
            answers = rows.loc[year_of == year, "y_season"]
            for name in RANKINGS:
                top = order[name][year].head(k)
                shares.loc[year, name] = float((top["y_season"] == 1).mean())
                funded[name].append(top["fips"].tolist())
            shares.loc[year, "random"] = float((answers == 1).mean())
            shares.loc[year, "oracle"] = min(k, int((answers == 1).sum())) / k
        per_k.append({"k": int(k), **_block(shares, draws, seed), "funded": funded})
        all_shares.append(shares)

    average = sum(all_shares) / len(all_shares)                # each year's shares, averaged over k
    return {"month": int(month), "ks": [int(k) for k in ks], "rows": int(len(rows)),
            "years": years, "n_years": len(years), "counties_per_year": [counties[y] for y in years],
            "per_k": per_k, "average_over_k": _block(average, draws, seed)}
