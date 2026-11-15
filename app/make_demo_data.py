"""
make_demo_data.py - builds FAKE handoff files. It is a test helper: tests/app/test_contract.py
uses it to build a fixture that has every column and key the contract requires.

Everything here is made up (random, seeded so it is repeatable). The files follow the
contract exactly - except metrics.json says DEMO DATA.

Run:  python app/make_demo_data.py [folder]
It only ever writes into the folder it is given (app/demo_data/ when no folder is given).
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Make "import app.contract" work when this file is run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.contract import (DEMO_DIR, LATEST_COLUMNS, MAP_COLUMNS, OUTLOOK_COLUMNS,  # noqa: E402
                          PRED_COLUMNS, validate_all)

SEED = 42                      # same seed = same fake data every time
FAKE_MAE = 8                   # fake "typical error" in weeks, used for the fake 12-month range
FAKE_FEED_COST = 35.66         # same placeholder price per head per month as the real handoff states
MISS_COST = 3                  # a missed drought costs 3x a false alarm (from the contract)
ALARM_LEVEL = 0.25             # warn when risk >= 25% (follows from the 3x cost rule)
rng = np.random.default_rng(SEED)

# One weekly date per Tuesday (Drought Monitor map dates), 2008 to mid Oct 2026.
DATES = pd.date_range("2008-01-01", "2026-10-13", freq="7D")
T = len(DATES)                 # number of weeks

# ---------------------------------------------------------------------------
# The fake geography: 40 made-up counties (12 Rio Grande + 7 on each other river).
# "wet" = long-run drought level the river drifts around (high = drier river).
# start/end = a rough line the county centers are spread along (lat, lon).
# ---------------------------------------------------------------------------
RIVERS = {
    "Rio Grande":  dict(n=12, wet=2.6, start=(37.5, -106.5), end=(26.0, -98.0),
                        states=[("Colorado", "08"), ("New Mexico", "35"), ("Texas", "48")]),
    "Colorado":    dict(n=7, wet=2.4, start=(40.0, -106.0), end=(32.0, -114.5),
                        states=[("Utah", "49"), ("Arizona", "04")]),
    "Missouri":    dict(n=7, wet=1.3, start=(47.5, -111.5), end=(38.5, -90.5),
                        states=[("Montana", "30"), ("Nebraska", "31"), ("Missouri", "29")]),
    "Mississippi": dict(n=7, wet=1.0, start=(47.0, -95.0), end=(30.0, -90.5),
                        states=[("Iowa", "19"), ("Illinois", "17"), ("Louisiana", "22")]),
    "Ohio":        dict(n=7, wet=0.6, start=(40.5, -80.0), end=(37.0, -89.0),
                        states=[("Ohio", "39"), ("Kentucky", "21"), ("Indiana", "18")]),
}


# ---------------------------------------------------------------------------
# Small helpers that turn a county's weekly drought class into the contract's columns
# ---------------------------------------------------------------------------
def streak(d2):
    """Consecutive weeks at D2 or worse, counting this week. 0 if not in D2."""
    out = np.zeros(len(d2), dtype=int)
    for t in range(len(d2)):
        if d2[t]:
            out[t] = (out[t - 1] + 1) if t > 0 else 1
    return out


def count_ahead(d2, k):
    """How many of the NEXT k weeks (t+1 .. t+k) are at D2 or worse. Only valid if t+k < T."""
    cs = np.concatenate([[0], np.cumsum(d2)])      # running total, so any window is a subtraction
    out = np.zeros(len(d2), dtype=int)
    for t in range(len(d2) - k):
        out[t] = cs[t + k + 1] - cs[t + 1]
    return out


def has_run_ahead(d2, k, run):
    """1 if the next k weeks contain `run` or more D2 weeks IN A ROW. Only valid if t+k < T."""
    out = np.zeros(len(d2), dtype=int)
    for t in range(len(d2) - k):
        best = cur = 0
        for w in d2[t + 1: t + k + 1]:
            cur = cur + 1 if w else 0
            best = max(best, cur)
        out[t] = int(best >= run)
    return out


def spell_lengths(d2):
    """Lengths of every run of consecutive severe-drought weeks, e.g. [3, 8, 2]."""
    runs, cur = [], 0
    for w in d2:
        if w:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    return runs


def past_weeks(d2, k):
    """How many of the last k weeks (counting this week) were at D2 or worse."""
    cs = np.concatenate([[0], np.cumsum(d2)])
    return np.array([cs[t + 1] - cs[max(0, t + 1 - k)] for t in range(len(d2))])


def tier_of(p):
    """Risk score -> Low / Watch / Warning. Low means 'no alarm' (below the 25% line)."""
    return np.where(p < ALARM_LEVEL, "Low", np.where(p < 0.5, "Watch", "Warning"))


def tally(df, alarm_col, truth_col):
    """Count alarms, hits, misses and false alarms, and the cost (3 x missed + false alarms)."""
    a, t = df[alarm_col].astype(bool), df[truth_col].astype(bool)
    caught, missed, false_alarms = int((a & t).sum()), int((~a & t).sum()), int((a & ~t).sum())
    alarms = int(a.sum())
    return dict(alarms=alarms, caught=caught, missed=missed, false_alarms=false_alarms,
                cost=MISS_COST * missed + false_alarms,
                precision=round(caught / alarms, 3) if alarms else None,
                recall=round(caught / (caught + missed), 3) if (caught + missed) else None)


def pct_cheaper(ours, other):
    """How much cheaper (in %) our cost is than another cost."""
    return round(100 * (other - ours) / other, 1) if other else 0.0


# ---------------------------------------------------------------------------
# Step 1: build one big table with every county, every week
# ---------------------------------------------------------------------------
def build_full_table():
    pieces = []
    for river, spec in RIVERS.items():
        # The whole river shares one slow "wetness" walk, so neighbors drought together.
        x = np.zeros(T)
        x[0] = spec["wet"]
        for t in range(1, T):
            x[t] = x[t - 1] + 0.15 * (spec["wet"] - x[t - 1]) + rng.normal(0, 0.45)

        for i in range(spec["n"]):
            state, code = spec["states"][i % len(spec["states"])]
            frac = i / max(spec["n"] - 1, 1)                      # 0..1 along the river
            lat = spec["start"][0] + frac * (spec["end"][0] - spec["start"][0]) + rng.normal(0, 0.3)
            lon = spec["start"][1] + frac * (spec["end"][1] - spec["start"][1]) + rng.normal(0, 0.3)

            # County drought class (0..5) = river walk + this county's own offset + a little noise.
            cls = np.clip(np.round(x + rng.normal(0, 0.4) + rng.normal(0, 0.35, T)), 0, 5).astype(int)
            d2 = cls >= 3                                          # D2 or worse = "severe drought"

            prev4 = np.concatenate([np.full(4, cls[0]), cls[:-4]])  # class 4 weeks earlier
            df = pd.DataFrame({
                "date": DATES,
                "fips": f"{code}{900 + i:03d}",                    # made-up 5-digit code
                "county": f"Demo County {river[:2].upper()}{i + 1}",
                "state": state, "river": river, "lat": lat, "lon": lon,
                "cls": cls,
                "d2_streak": streak(d2),
                # --- truths (a future we only know for weeks that are old enough) ---
                "y": (count_ahead(d2, 4) > 0).astype(int),
                "y_season": has_run_ahead(d2, 26, 8),
                "y_weeks": count_ahead(d2, 52),
                # --- baselines, straight from today's class ---
                "alarm_persistence": d2,
                "alarm_d1_now": cls >= 2,
                "alarm_worsening": d2 | ((cls == 2) & (cls > prev4)),
                "weeks_last_year": past_weeks(d2, 52).astype(float),
                "weeks_same_as_now": np.where(d2, 52.0, 0.0),
            })
            df["ok4"] = np.arange(T) < T - 4       # is the 4-week future known yet?
            df["ok52"] = np.arange(T) < T - 52     # is the 52-week future known yet?
            pieces.append(df)
    return pd.concat(pieces, ignore_index=True)


# ---------------------------------------------------------------------------
# Step 2: cut the big table into the three contract files
# ---------------------------------------------------------------------------
def build_predictions(full):
    p = full[(full["date"] >= "2019-01-01") & full["ok4"]].copy()

    # "Typical for the time of year" baseline: weeks of the year that were risky before 2019.
    full_week = full["date"].dt.isocalendar().week.astype(int)
    old = full[(full["date"] < "2019-01-01") & full["ok4"]]
    risk = old.groupby(["river", full_week[old.index]])["y"].mean()
    risky = {k for k, v in risk.items() if v >= 0.5}
    weeks = p["date"].dt.isocalendar().week.astype(int)
    p["alarm_calendar"] = [(r, w) in risky for r, w in zip(p["river"], weeks)]

    # Fake "model": a risk score loosely tied to today's class and to what really happened.
    p["p_model"] = np.clip(0.12 * p["cls"] + 0.25 * p["y"] + rng.normal(0, 0.08, len(p)), 0, 1)
    p["tier"] = tier_of(p["p_model"])
    p["alarm_system"] = p["tier"] != "Low"

    p = p.sort_values(["date", "fips"], kind="stable").reset_index(drop=True)
    return p[[c for c, _ in PRED_COLUMNS]]


def build_outlook(full):
    # Issue dates = first Drought Monitor week of each month, 2008 to 2025, full year ahead known.
    o = full[(full["date"].dt.day <= 7) & (full["date"].dt.year <= 2025) & full["ok52"]].copy()
    o = o.sort_values(["fips", "date"], kind="stable")

    # Fake model scores.
    o["p_season"] = np.clip(0.10 * o["cls"] + 0.30 * o["y_season"] + rng.normal(0, 0.08, len(o)), 0, 1)
    o["alarm_season"] = o["p_season"] >= ALARM_LEVEL
    o["alarm_season_persistence"] = o["alarm_persistence"]
    o["alarm_season_d1"] = o["alarm_d1_now"]
    o["weeks_usual"] = np.nan                                       # filled in just below

    # "Usual for this county" = average over this county's EARLIER issue dates.
    by_county = o.groupby("fips")
    o["p_season_usual"] = by_county["y_season"].transform(lambda s: s.shift().expanding().mean()).fillna(0.5)
    o["weeks_usual"] = by_county["y_weeks"].transform(lambda s: s.shift().expanding().mean()).fillna(22.0)
    o["weeks_model"] = np.clip(0.6 * o["y_weeks"] + 0.4 * o["weeks_usual"] + rng.normal(0, 6, len(o)), 0, 52)

    # Canal pivot (optional column, fake): the same score nudged a little, as if the forest also saw reservoirs.
    o["p_season_res"] = np.clip(o["p_season"] + rng.normal(0, 0.03, len(o)), 0, 1)

    o = o.sort_values(["date", "fips"], kind="stable").reset_index(drop=True)
    return o[[c for c, _ in OUTLOOK_COLUMNS] + ["p_season_res"]]


def build_latest(full, outlook):
    last = full[full["date"] == DATES[-1]].copy()               # the most recent week
    last["p_model"] = np.clip(0.12 * last["cls"] + rng.normal(0, 0.08, len(last)), 0, 1)
    last["tier"] = tier_of(last["p_model"])
    last["alarm_system"] = last["tier"] != "Low"
    last["p_season"] = np.clip(0.10 * last["cls"] + 0.15 + rng.normal(0, 0.08, len(last)), 0, 1)
    last["season_tier"] = tier_of(last["p_season"])
    usual = outlook.groupby("fips")["weeks_usual"].last()
    last["weeks_usual"] = last["fips"].map(usual)
    last["weeks_model"] = np.clip(last["weeks_usual"] + 6 * (last["cls"] - 2), 0, 52)
    last = last.sort_values("fips", kind="stable").reset_index(drop=True)

    # --- the optional map columns (same names and meaning as the real handoff) ---
    order = {"Low": 0, "Watch": 1, "Warning": 2}
    last["risk_level"] = [a if order[a] >= order[b] else b for a, b in zip(last["tier"], last["season_tier"])]
    last["weeks_low"] = np.clip(last["weeks_model"] - FAKE_MAE, 0, 52)
    last["weeks_high"] = np.clip(last["weeks_model"] + FAKE_MAE, 0, 52)
    spells = {f: spell_lengths(g["cls"].to_numpy() >= 3) for f, g in full.groupby("fips")}
    last["typical_drought_weeks"] = [float(np.median(spells[f])) if spells[f] else 0.0 for f in last["fips"]]
    last["longest_drought_weeks"] = [float(max(spells[f])) if spells[f] else 0.0 for f in last["fips"]]
    last["damage_months"] = last["weeks_model"] / 4.345
    last["damage_usd_per_100_head"] = last["damage_months"] * FAKE_FEED_COST * 100

    # --- the optional canal-pivot columns (fake) ---
    last["p_season_res"] = np.clip(last["p_season"] + rng.normal(0, 0.03, len(last)), 0, 1)
    last["d2_share_history"] = np.clip(0.08 * last["cls"] + 0.10 + rng.normal(0, 0.03, len(last)), 0, 1)
    # Fake reservoirs: the first 4 Rio Grande counties get Elephant Butte, the next 4 Amistad-Falcon.
    rio = last.index[last["river"] == "Rio Grande"].to_list()
    last["res_name"] = "none"
    last.loc[rio[:4], "res_name"] = "Elephant Butte"
    last.loc[rio[4:8], "res_name"] = "Amistad-Falcon"
    last["res_pct_full"] = np.where(last["res_name"] == "none", -1.0, 35.0)   # -1 = no reservoir
    columns = ([c for c, _ in LATEST_COLUMNS] + MAP_COLUMNS
               + ["p_season_res", "d2_share_history", "res_name", "res_pct_full"])
    return last[columns]


# ---------------------------------------------------------------------------
# Step 3: metrics.json - the counts are computed from the fake rows so they add up.
# Anything we can't compute sensibly is a fixed fake number.
# ---------------------------------------------------------------------------
def best_of(costs):
    """Cheapest of {name: cost}. Returns (name, cost)."""
    name = min(costs, key=costs.get)
    return name, costs[name]


def build_metrics(pred, outlook, latest):
    focus = pred[pred["river"] == "Rio Grande"]

    # --- 4-week alert: one policy per alarm column ---
    policy_cols = [("Our system", "alarm_system"), ("Persistence (D2 or worse now)", "alarm_persistence"),
                   ("D1 or worse now", "alarm_d1_now"), ("Worsening", "alarm_worsening"),
                   ("Typical for the time of year", "alarm_calendar")]
    policies = []
    for name, col in policy_cols:
        t = tally(focus, col, "y")
        policies.append(dict(name=name, column=col, cost=t["cost"], precision=t["precision"],
                             recall=t["recall"], alarms=t["alarms"], caught=t["caught"],
                             missed=t["missed"], false_alarms=t["false_alarms"],
                             auc=0.8 if col == "alarm_system" else None))
    cost = {p["column"]: p["cost"] for p in policies}
    base_name, base_cost = best_of({k: v for k, v in cost.items() if k != "alarm_system"})

    # --- per-river 4-week table (all five rivers) ---
    per_river = []
    for river in pred["river"].unique():
        r = pred[pred["river"] == river]
        sysc, pers, d1 = tally(r, "alarm_system", "y"), tally(r, "alarm_persistence", "y"), tally(r, "alarm_d1_now", "y")
        rule, rule_cost = ("Persistence", pers["cost"]) if pers["cost"] <= d1["cost"] else ("D1 now", d1["cost"])
        per_river.append(dict(river=river, counties=int(r["fips"].nunique()), system_cost=sysc["cost"],
                              persistence_cost=pers["cost"], best_rule=rule, best_rule_cost=rule_cost,
                              pct_cheaper_than_best_rule=pct_cheaper(sysc["cost"], rule_cost),
                              own_river_cost=sysc["cost"] if river == "Rio Grande" else int(sysc["cost"] * 0.95),
                              precision=sysc["precision"], recall=sysc["recall"], auc=0.78))

    # --- year by year (focus river) ---
    year_by_year = []
    for yr, g in focus.groupby(focus["date"].dt.year):
        year_by_year.append(dict(year=int(yr), positives=int(g["y"].sum()),
                                 system_cost=tally(g, "alarm_system", "y")["cost"],
                                 persistence_cost=tally(g, "alarm_persistence", "y")["cost"]))

    # --- 6-month outlook ---
    out_focus = outlook[outlook["river"] == "Rio Grande"]
    s = {c: tally(out_focus, c, "y_season") for c in
         ("alarm_season", "alarm_season_persistence", "alarm_season_d1")}
    out_focus = out_focus.assign(alarm_season_usual=out_focus["p_season_usual"] >= ALARM_LEVEL)
    usual_cost = tally(out_focus, "alarm_season_usual", "y_season")["cost"]
    n_pos = int(out_focus["y_season"].sum())
    n_neg = len(out_focus) - n_pos
    season_costs = dict(persistence=s["alarm_season_persistence"]["cost"],
                        d1=s["alarm_season_d1"]["cost"], usual=usual_cost)

    def season_row(river):                       # one line of season.per_river
        r = outlook[outlook["river"] == river].assign()
        r["alarm_season_usual"] = r["p_season_usual"] >= ALARM_LEVEL
        sysc = tally(r, "alarm_season", "y_season")["cost"]
        pers = tally(r, "alarm_season_persistence", "y_season")["cost"]
        d1 = tally(r, "alarm_season_d1", "y_season")["cost"]
        rule, rule_cost = ("Persistence", pers) if pers <= d1 else ("D1 now", d1)
        return dict(river=river, system_cost=sysc, persistence_cost=pers, best_rule=rule,
                    best_rule_cost=rule_cost, pct_cheaper_than_best_rule=pct_cheaper(sysc, rule_cost),
                    own_river_cost=sysc if river == "Rio Grande" else int(sysc * 0.95))

    season = dict(
        horizon_weeks=26,
        target="8 or more consecutive weeks at D2 or worse inside the next 26 weeks",
        test_years=[2008, 2025], threshold=ALARM_LEVEL,
        focus=dict(rows=len(out_focus), base_rate=round(n_pos / len(out_focus), 3),
                   precision=s["alarm_season"]["precision"], recall=s["alarm_season"]["recall"], auc=0.8,
                   system_cost=s["alarm_season"]["cost"], persistence_cost=season_costs["persistence"],
                   d1_rule_cost=season_costs["d1"], usual_cost=usual_cost,
                   always_warn_cost=n_neg, never_warn_cost=MISS_COST * n_pos,
                   pct_cheaper_than_persistence=pct_cheaper(s["alarm_season"]["cost"], season_costs["persistence"]),
                   beats_every_baseline=bool(s["alarm_season"]["cost"] < min(season_costs.values())),
                   years_better_than_usual="10/18"),                      # fixed fake value
        per_river=[season_row(r) for r in pred["river"].unique()])

    # --- 12-month outlook (mean absolute error, in weeks) ---
    def mae(df, col):
        return round(float((df[col] - df["y_weeks"]).abs().mean()), 1)

    def year_row(river):                         # one line of year.per_river
        r = outlook[outlook["river"] == river]
        base = {"Same as now": mae(r, "weeks_same_as_now"), "Same as last year": mae(r, "weeks_last_year"),
                "Usual": mae(r, "weeks_usual")}
        name, val = best_of(base)
        m = mae(r, "weeks_model")
        return dict(river=river, mae_system=m, best_baseline=name, mae_best_baseline=val,
                    mae_own_river=m if river == "Rio Grande" else round(m * 0.95, 1))

    year = dict(
        horizon_weeks=52, target="number of weeks at D2 or worse in the next 52 weeks",
        test_years=[2008, 2025],
        focus=dict(rows=len(out_focus), mean_weeks=round(float(out_focus["y_weeks"].mean()), 1),
                   mae_system=mae(out_focus, "weeks_model"), mae_same_as_now=mae(out_focus, "weeks_same_as_now"),
                   mae_last_year=mae(out_focus, "weeks_last_year"), mae_usual=mae(out_focus, "weeks_usual"),
                   beats_every_baseline=bool(mae(out_focus, "weeks_model") < min(
                       mae(out_focus, "weeks_same_as_now"), mae(out_focus, "weeks_last_year"),
                       mae(out_focus, "weeks_usual"))),
                   years_better_than_last_year="9/18", years_better_than_usual="11/18"),  # fixed fake values
        per_river=[year_row(r) for r in pred["river"].unique()])

    # --- failure examples: a real miss and a real false alarm from the fake rows ---
    failures = []
    miss = focus[(focus["y"] == 1) & (~focus["alarm_system"])].head(1)
    false = focus[(focus["y"] == 0) & (focus["alarm_system"])].head(1)
    for kind, rows in (("miss", miss), ("false alarm", false)):
        for _, r in rows.iterrows():
            text = ("DEMO: the system stayed quiet but severe drought arrived within 4 weeks." if kind == "miss"
                    else "DEMO: the system warned but severe drought did not arrive within 4 weeks.")
            failures.append(dict(product="4-week alert", date=str(r["date"].date()),
                                 county=r["county"], state=r["state"], what_happened=text))
    while len(failures) < 2:                    # the contract wants at least two entries
        failures.append(dict(product="4-week alert", date="2022-05-03", county="Demo County", state="New Mexico",
                             what_happened="DEMO: placeholder failure example."))

    return dict(
        contract_version=2, generated_at=pd.Timestamp.now(tz="UTC").isoformat(timespec="seconds"),
        is_final=False, focus_river="Rio Grande", training_scope="Rio Grande counties only (DEMO)",
        n_rows=len(pred), n_focus_rows=len(focus), n_counties=int(pred["fips"].nunique()),
        n_focus_counties=int(focus["fips"].nunique()), horizon_weeks=4,
        train_years=[2000, 2014], val_years=[2015, 2018], test_years=[2019, 2026],
        latest_week=str(latest["date"].iloc[0].date()), miss_cost=MISS_COST,
        policies=policies,
        headline=dict(system_cost=cost["alarm_system"], persistence_cost=cost["alarm_persistence"],
                      pct_cheaper_than_persistence=pct_cheaper(cost["alarm_system"], cost["alarm_persistence"]),
                      cheapest_baseline_on_test=base_name, cheapest_baseline_cost=base_cost,
                      honesty_check_pass=bool(cost["alarm_system"] < base_cost)),
        onset=dict(rows=1000, positives=120, system_cost=300, best_rule="D1 now", best_rule_cost=310,
                   never_warn_cost=360, precision=0.4, recall=0.3, auc=0.7),           # fixed fake values
        events=dict(n=20, warned_within_4_weeks=9, median_lead_weeks=2.0),               # fixed fake values
        cost_sensitivity=[dict(miss_cost=2, system_cost=cost["alarm_system"], best_baseline_cost=base_cost)],
        year_by_year=year_by_year, per_river=per_river, season=season, year=year,
        failure_examples=failures, shuffled_auc_mean=0.5,
        ablations=[dict(name="DEMO: without the Pacific El Nino index", product="6-month outlook",
                        result="DEMO: no change in cost.")],
        feature_importance=[dict(feature="nb_mean", importance=0.4), dict(feature="cls", importance=0.3)],
        limits=["DEMO DATA - these are not real results"],
        map_fields=dict(
            columns={c: "DEMO: fake map column" for c in MAP_COLUMNS},
            feed_cost_per_head_month=FAKE_FEED_COST,
            feed_cost_source="DEMO placeholder, not a real source",
            tested="DEMO DATA - these are not real estimates."),
        # Canal pivot blocks: all fixed fake numbers, labeled DEMO.
        trigger=dict(
            issue_months=[1, 2, 3], threshold=0.25, rows=120, drought_seasons=30,
            rules=[dict(name=n, fires=f, caught=c, missed=30 - c, false_alarms=f - c,
                        recall=c / 30, precision=c / f)
                   for n, f, c in [("Our forecast", 40, 24), ("Our forecast with reservoirs", 38, 24),
                                   ("D1 or worse now", 50, 25), ("D2 or worse now", 30, 18),
                                   ("Seal every year", 120, 30)]],
            value_sweep=[dict(cost_ratio=r, forecast=0.50 - r, forecast_reservoir=0.495 - r, d1_rule=0.497 - r,
                              persistence=0.40 - r, seal_every_year=0.50 - r) for r in (0.02, 0.05, 0.10, 0.25, 0.50)],
            forecast_beats_d1_rule=True, reservoir_forecast_beats_d1_rule=False),
        reservoir=dict(
            systems=[dict(name="Amistad-Falcon", counties=4, first_date="2000-01-01", last_date="2026-10-13"),
                     dict(name="Elephant Butte", counties=4, first_date="2000-01-01", last_date="2026-10-13")],
            counties_without_reservoir=4,
            note="DEMO DATA - counties were matched to reservoirs at random."),
        losses=dict(
            source="DEMO DATA, not the real USDA files", years=[2000, 2025], causes_included=["Drought"],
            total_usd=1_000_000, by_year=[dict(year=y, usd=50_000 * (y - 1999)) for y in range(2000, 2026, 5)],
            by_county=[dict(fips="48215", county="Demo County", state="Texas", usd=400_000)],
            note="DEMO DATA. Insured losses only. Not all drought losses."),
    )


def native(o):
    """json.dump helper: turn numpy numbers into plain Python numbers."""
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    raise TypeError(f"cannot save {type(o)}")


def main(out_dir=None):
    """Write the four fake files into out_dir (app/demo_data/ when no folder is given)."""
    out_dir = DEMO_DIR if out_dir is None else Path(out_dir)
    full = build_full_table()
    pred = build_predictions(full)
    outlook = build_outlook(full)
    latest = build_latest(full, outlook)
    metrics = build_metrics(pred, outlook, latest)

    # Safety: only ever write inside the one folder.
    out_dir.mkdir(parents=True, exist_ok=True)
    pred.to_parquet(out_dir / "predictions.parquet", index=False)
    outlook.to_parquet(out_dir / "outlook.parquet", index=False)
    latest.to_parquet(out_dir / "latest.parquet", index=False)
    with open(out_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=native)

    # Check our own fake files against the contract before declaring victory.
    problems = validate_all(*[pd.read_parquet(out_dir / f"{n}.parquet") for n in ("predictions", "outlook", "latest")],
                            json.load(open(out_dir / "metrics.json", encoding="utf-8")))
    print(f"predictions {len(pred)} rows | outlook {len(outlook)} rows | latest {len(latest)} rows")
    print("contract problems:", problems if problems else "none")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
