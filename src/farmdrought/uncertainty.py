"""
uncertainty.py - how sure are we that policy A really differs from policy B?

ADDED in round 3 (ARCHITECTURE.md section 3.1). It changes no version 1 number: it only puts
an interval around a difference that is already reported.

The method is a paired bootstrap over whole calendar years. Rows from the same year are not
independent (one dry year moves every county at once), so the unit that is drawn again and
again is the YEAR, never the row. The same drawn years are used for A and for B, so the
interval is for the difference between them on the same years.

HOW FAR TO TRUST THE INTERVAL. It is a plain percentile interval, and with as few years as this
project has (8 for the alert, 18 for the outlooks) a percentile interval is too narrow. In a
simulation with independent years and a true difference of zero, run during review on
2026-11-15 (a simulation, NOT this project's data), a nominal 95% interval covered the truth
about 88% of the time with 8 years and 92% with 18 (80% and 90% with two-year blocks). Years
that depend on each other make it narrower still. Every result therefore carries a "caveat"
saying so, and every report that prints an interval must print n_years and that caveat beside it.

DIRECTION. Some quantities are better when lower (a cost, an error), some when higher (a share
of funded counties that were right). Every caller must say which, with lower_is_better. Use
direction(result) when the question is "did A win?"; excludes_zero only says the two differ.
"""
import numpy as np
import pandas as pd


CAVEAT = ("Percentile interval from {n_years} resampled years (block {block}). With this few years it is "
          "too narrow: in simulation a nominal 95% interval covered the truth about 88% of the time with "
          "8 years and 92% with 18 (80% and 90% with two-year blocks), and is expected to be less if years "
          "are dependent. These coverage figures come from a simulation with independent years and a true "
          "difference of zero, not from this project's data.")
MIN_DRAWS = 200   # with fewer resamples the 2.5 and 97.5 percentiles rest on a handful of draws


def _by_year(values, name):
    """A float Series sorted by year. Refuses a year that appears twice and any value that is
    missing or infinite (it would pass silently into every resample that drew that year)."""
    series = pd.Series(values, dtype=float).sort_index()
    if series.index.has_duplicates:
        raise ValueError(f"{name}: a year appears more than once")
    bad = series.index[~np.isfinite(series.to_numpy())].tolist()
    if bad:
        raise ValueError(f"{name}: missing or infinite value in year(s) {bad}")
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
             overlap (years 1+2, 3+4, ...). Whole pairs are drawn with replacement, n_years / 2
             of them, which gives exactly n_years years.
    Why block=2 exists: a 26- or 52-week answer window that starts late in one year ends in the
    next, so two neighbouring years share some of the same weeks and are not independent.
    Drawing them together keeps that link inside each resample.

    Refused with a ValueError:
      - fewer than two units to draw from (one year, or one pair). Every resample would then be
        the original, the interval would have no width, and it would look like a certain result.
      - block=2 with an odd number of years. The last year would be a block of its own, the
        drawn list would have to be cut to n_years, and the cut makes inclusion uneven: the
        first year of the pair that is cut is kept and the second dropped, so first years are
        over-represented. A biased interval is worse than none. The project's series have 8 and
        18 years, both even.
    """
    if block not in (1, 2):
        raise ValueError(f"block must be 1 or 2, got {block}")
    if block == 2 and n_years % 2:
        raise ValueError(f"block=2 needs an even number of years, got {n_years}")
    if n_years // block < 2:
        raise ValueError(f"need at least two units to resample, got {n_years} year(s) with block={block}")
    if block == 1:
        return rng.integers(0, n_years, size=(draws, n_years))
    first_years = 2 * rng.integers(0, n_years // 2, size=(draws, n_years // 2))   # first year of each drawn pair
    return np.stack([first_years, first_years + 1], axis=2).reshape(draws, n_years)


def year_block_bootstrap(per_year_a, per_year_b, weights=None, draws=10000, seed=0, block=1, *,
                         lower_is_better):
    """
    Interval for (policy A minus policy B), resampling whole calendar years.

    per_year_a, per_year_b: one number per calendar year for each policy (a pandas Series
    indexed by year, or a dict {year: number}). Both must cover exactly the same years.

    lower_is_better (required, by name): True for a cost or an error, False for a quantity where
    more is better (a share of correct picks). It has no default, so every caller states it.
    It decides what "A better" means below: A strictly lower than B when True, A strictly
    higher than B when False. It never changes diff, lo or hi, which are always A minus B.

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
      share_draws_a_better  share of resamples where A's statistic is strictly better than B's
      years_a_better        how many original years have A's number strictly better than B's
      lower_is_better       as given
      n_years, draws, block, seed
      caveat                why the interval is too narrow with this few years (print it)

    Raises ValueError for: years that do not match, a missing or infinite value, a weight at
    or below zero, fewer than 200 draws, fewer than two units to resample, or block=2 with an
    odd number of years (see resample_years).
    """
    if not isinstance(lower_is_better, (bool, np.bool_)):
        raise ValueError(f"lower_is_better must be True or False, got {lower_is_better!r}")
    a, b = _by_year(per_year_a, "per_year_a"), _by_year(per_year_b, "per_year_b")
    _check_same_years(a, b, "per_year_a", "per_year_b")
    if weights is not None:
        w = _by_year(weights, "weights")
        _check_same_years(a, w, "per_year_a", "weights")
        if not (w > 0).all():
            raise ValueError("weights must all be above zero")
    if len(a) == 0:
        raise ValueError("there are no years to resample")
    if draws < MIN_DRAWS:
        raise ValueError(f"draws must be at least {MIN_DRAWS}, got {draws}")

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
    if lower_is_better:
        draws_a_better, years_a_better = stat_a < stat_b, a_values < b_values
    else:
        draws_a_better, years_a_better = stat_a > stat_b, a_values > b_values
    return {"diff": float(diff), "lo": float(lo), "hi": float(hi),
            "share_draws_a_better": float(draws_a_better.mean()),
            "years_a_better": int(years_a_better.sum()),
            "lower_is_better": bool(lower_is_better),
            "n_years": int(len(a)), "draws": int(draws), "block": int(block), "seed": int(seed),
            "caveat": CAVEAT.format(n_years=len(a), block=block)}


def excludes_zero(result):
    """TWO-SIDED: True when the interval is wholly below zero OR wholly above zero.

    So it says "A and B differ", not "A won": a clear loss also returns True. Use
    direction(result) when the question is who won. An interval that touches zero (lo or hi
    exactly 0) returns False. This is the test behind "a win needs an interval"
    (ARCHITECTURE.md rule 0.5).
    """
    return (result["lo"] < 0 and result["hi"] < 0) or (result["lo"] > 0 and result["hi"] > 0)


def direction(result):
    """Who won, in words: "a better", "b better" or "not separated".

    Uses the interval for A minus B and the result's own lower_is_better. When lower is better,
    an interval wholly below zero means A is better; when higher is better, an interval wholly
    above zero does. An interval that reaches or crosses zero is "not separated". Callers must
    use this, not excludes_zero, when they mean "a win".
    """
    if not excludes_zero(result):
        return "not separated"
    a_is_lower = result["hi"] < 0
    return "a better" if a_is_lower == result["lower_is_better"] else "b better"
