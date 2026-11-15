"""
uncertainty.py - how sure are we that policy A really differs from policy B?

ADDED in round 3 (ARCHITECTURE.md section 3.1). It changes no version 1 number: it only puts
an interval around a difference that is already reported.

The method is a paired bootstrap over whole calendar years. Rows from the same year are not
independent (one dry year moves every county at once), so the unit that is drawn again and
again is the YEAR, never the row. The same drawn years are used for A and for B, so the
interval is for the difference between them on the same years.
"""
import numpy as np
import pandas as pd


def _by_year(values, name):
    """A float Series sorted by year. Refuses a year that appears twice."""
    series = pd.Series(values, dtype=float).sort_index()
    if series.index.has_duplicates:
        raise ValueError(f"{name}: a year appears more than once")
    return series


def _check_same_years(first, other, first_name, other_name):
    """Raise a ValueError that names the years one input has and the other lacks."""
    if first.index.equals(other.index):
        return
    only_first = sorted(set(first.index) - set(other.index))
    only_other = sorted(set(other.index) - set(first.index))
    raise ValueError(f"year indexes do not match: only in {first_name}: {only_first}; "
                     f"only in {other_name}: {only_other}")


def resample_years(n_years, draws, rng, block=1):
    """
    Which years go into each resample. Returns an integer array of shape (draws, n_years):
    each row holds positions (0 = the earliest year) drawn with replacement.

    block=1: single years are drawn.
    block=2: the years, in sorted order, are first cut into consecutive pairs that do not
             overlap (years 1+2, 3+4, ...; with an odd count the last year is a block of its
             own). Whole blocks are drawn with replacement until at least n_years years have
             been drawn, and the list is then cut to n_years.
    Why block=2 exists: a 26- or 52-week answer window that starts late in one year ends in the
    next, so two neighbouring years share some of the same weeks and are not independent.
    Drawing them together keeps that link inside each resample.
    """
    if block not in (1, 2):
        raise ValueError(f"block must be 1 or 2, got {block}")
    if block == 1:
        return rng.integers(0, n_years, size=(draws, n_years))
    blocks = [list(range(start, min(start + 2, n_years))) for start in range(0, n_years, 2)]
    out = np.empty((draws, n_years), dtype=int)
    for d in range(draws):
        # n_years blocks always hold at least n_years years, so taking the first n_years of
        # them is the same as drawing blocks one at a time until there are enough.
        picked = rng.integers(0, len(blocks), size=n_years)
        out[d] = [year for b in picked for year in blocks[b]][:n_years]
    return out


def year_block_bootstrap(per_year_a, per_year_b, weights=None, draws=10000, seed=0, block=1):
    """
    Interval for (policy A minus policy B), resampling whole calendar years.

    per_year_a, per_year_b: one number per calendar year for each policy (a pandas Series
    indexed by year, or a dict {year: number}). Both must cover exactly the same years.

    LOWER IS BETTER for every quantity this project compares (a cost, an error in weeks), so
    "A better" always means "A's number is strictly lower than B's".

    Two modes, chosen by `weights`:
      weights=None   The numbers are yearly TOTALS (for example a cost). The statistic of a
                     resample is the SUM over the years in it.
      weights given  The numbers are per-row AVERAGES within each year (for example a mean
                     error). `weights` holds one positive number per year, usually how many
                     rows that year has, and the statistic of a resample is the WEIGHTED
                     MEAN over the years in it. A year drawn twice counts twice.

    draws: how many resamples. seed: numpy default_rng(seed), so the same seed always gives
    the same answer. block: 1 draws single years, 2 draws adjacent pairs (see resample_years).

    Returns a dict of plain Python numbers (safe for json.dump):
      diff                  statistic of A minus statistic of B on the original years
      lo, hi                2.5 and 97.5 percentiles of that difference over the resamples
      share_draws_a_better  share of resamples where A's statistic is strictly lower than B's
      years_a_better        how many original years have A's number strictly lower than B's
      n_years, draws, block, seed
    """
    a, b = _by_year(per_year_a, "per_year_a"), _by_year(per_year_b, "per_year_b")
    _check_same_years(a, b, "per_year_a", "per_year_b")
    if weights is not None:
        w = _by_year(weights, "weights")
        _check_same_years(a, w, "per_year_a", "weights")
        if not (w > 0).all():
            raise ValueError("weights must all be above zero")
    if len(a) == 0:
        raise ValueError("there are no years to resample")
    if draws < 1:
        raise ValueError(f"draws must be at least 1, got {draws}")

    a_values, b_values = a.to_numpy(), b.to_numpy()
    picked = resample_years(len(a), draws, np.random.default_rng(seed), block)
    if weights is None:
        stat_a, stat_b = a_values[picked].sum(axis=1), b_values[picked].sum(axis=1)
        diff = a_values.sum() - b_values.sum()
    else:
        w_values = w.to_numpy()
        total = w_values[picked].sum(axis=1)
        stat_a = (a_values * w_values)[picked].sum(axis=1) / total
        stat_b = (b_values * w_values)[picked].sum(axis=1) / total
        diff = ((a_values * w_values).sum() - (b_values * w_values).sum()) / w_values.sum()
    lo, hi = np.percentile(stat_a - stat_b, [2.5, 97.5])
    return {"diff": float(diff), "lo": float(lo), "hi": float(hi),
            "share_draws_a_better": float((stat_a < stat_b).mean()),
            "years_a_better": int((a_values < b_values).sum()),
            "n_years": int(len(a)), "draws": int(draws), "block": int(block), "seed": int(seed)}


def excludes_zero(result):
    """
    True only when the whole interval is on one side of zero: lo and hi both strictly below
    zero, or both strictly above. This is the project's meaning of "a win needs an interval"
    (ARCHITECTURE.md rule 0.5). An interval that touches zero is not a win.
    """
    return (result["lo"] < 0 and result["hi"] < 0) or (result["lo"] > 0 and result["hi"] > 0)
