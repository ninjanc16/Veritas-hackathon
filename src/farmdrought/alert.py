"""alert.py: the 4-week alert and the transfer test.

Question, for each county each week:
    "Will this county reach severe drought (D2 or worse) in any of the next 4 weeks?"

What this file does:
  1. Split the rows by TIME into train, validation and test.
  2. Train a random forest on Rio Grande counties only.
  3. Pick the alarm threshold on validation years.
  4. Score the test years: Rio Grande first, then the other four rivers (the transfer test).
  5. Train comparison models, to see what a different choice would have given.

Run it with:  PYTHONPATH=src python -m farmdrought.alert
"""
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from farmdrought.baselines import BASELINES, add_baselines
from farmdrought.config import ALERT_WEEKS, D2_CLASS, FOCUS_RIVER, MISS_COST, RIVERS, TEST_START, TRAIN, VAL
from farmdrought.drought import build_panel
from farmdrought.evaluate import events, pick_threshold, tally
from farmdrought.features import FEATURES_H


def split_masks(panel):
    """Split rows by time. Returns three True/False masks: train, val, test.

    A row's answer depends on the 4 weeks AFTER its date. So a row only belongs to a
    block if that whole 4-week window ends inside the block. This stops a training row
    from "seeing" validation weeks, and a validation row from seeing test weeks.
    """
    has_truth = panel["y"].notna()  # the newest weeks have no answer yet
    window_end = panel["date"] + pd.Timedelta(weeks=ALERT_WEEKS)
    train_end = pd.Timestamp(f"{TRAIN[1]}-12-31")
    val_end = pd.Timestamp(f"{VAL[1]}-12-31")
    train = has_truth & (window_end <= train_end)
    val = has_truth & (panel["date"] > train_end) & (window_end <= val_end)
    test = has_truth & (panel["date"] >= pd.Timestamp(f"{TEST_START}-01-01"))
    return train, val, test


def make_forest():
    """The 4-week forest. Settings were fixed before the build (architecture doc, P5)."""
    return RandomForestClassifier(
        n_estimators=100,        # 100 trees vote
        max_depth=12,            # each tree asks at most 12 questions in a row
        min_samples_leaf=100,    # each final group holds 100+ rows, so no memorizing
        max_features="sqrt",     # each split looks at a random few inputs
        class_weight="balanced_subsample",  # drought and no-drought rows count equally
        random_state=0,          # same result every run
        n_jobs=-1,               # use all CPU cores
    )


def fit_alert(panel, train, val, model=None):
    """Train a model on the train rows, then pick its alarm threshold on the val rows.

    Returns (model, threshold). Test rows are never used here.
    """
    model = model or make_forest()
    model.fit(panel.loc[train, FEATURES_H], panel.loc[train, "y"])
    val_score = model.predict_proba(panel.loc[val, FEATURES_H])[:, 1]
    return model, pick_threshold(val_score, panel.loc[val, "y"])


def shuffled_auc(panel, train, test, runs=3):
    """Honesty check: train on SHUFFLED answers. The model should then learn nothing,
    so its test AUC should be close to 0.5 (a coin flip). If it is much higher, the
    answers are leaking into the inputs somewhere.
    """
    scores = []
    for seed in range(runs):
        shuffled = panel.loc[train, "y"].sample(frac=1, random_state=seed).values
        model = make_forest().fit(panel.loc[train, FEATURES_H], shuffled)
        p = model.predict_proba(panel.loc[test, FEATURES_H])[:, 1]
        scores.append(roc_auc_score(panel.loc[test, "y"], p))
    return float(np.mean(scores))


def run_alert():
    """Run the whole 4-week experiment. Returns (panel with scores and alarms, results)."""
    panel = build_panel()
    train, val, test = split_masks(panel)
    focus = panel["river"] == FOCUS_RIVER
    panel = add_baselines(panel, train, val)

    # ---- Our system: forest trained on Rio Grande rows only ----
    model, threshold = fit_alert(panel, train & focus, val & focus)
    panel["p_model"] = model.predict_proba(panel[FEATURES_H])[:, 1]
    panel["alarm_system"] = panel["p_model"] >= threshold

    # ---- Comparison models (not the system, just to compare) ----
    # (a) a forest retrained on each river's own counties
    panel["alarm_own_river"] = panel["alarm_system"]  # for the Rio Grande it is the same model
    for river in RIVERS:
        if river != FOCUS_RIVER:
            on_river = panel["river"] == river
            own, own_thr = fit_alert(panel, train & on_river, val & on_river)
            panel.loc[on_river, "alarm_own_river"] = own.predict_proba(panel.loc[on_river, FEATURES_H])[:, 1] >= own_thr
    # (b) one forest trained on all five rivers
    pooled, pooled_thr = fit_alert(panel, train, val)
    panel["alarm_all_rivers"] = pooled.predict_proba(panel[FEATURES_H])[:, 1] >= pooled_thr
    # (c) logistic regression on Rio Grande rows. It needs inputs on the same scale, so
    #     subtract the training mean and divide by the training spread.
    mean = panel.loc[train & focus, FEATURES_H].mean()
    spread = panel.loc[train & focus, FEATURES_H].std() + 1e-9
    scaled = panel.copy()
    scaled[FEATURES_H] = (panel[FEATURES_H] - mean) / spread
    logit, logit_thr = fit_alert(scaled, train & focus, val & focus,
                                 LogisticRegression(max_iter=300, C=0.5, class_weight="balanced"))
    panel["alarm_logistic"] = logit.predict_proba(scaled[FEATURES_H])[:, 1] >= logit_thr

    # =================== Results. Test rows only from here on ===================
    rg = panel[test & focus]  # Rio Grande test rows: the headline numbers

    # ---- Our system against every baseline, on the Rio Grande ----
    policies = [{"name": "Our system", "column": "alarm_system", **tally(rg["y"], rg["alarm_system"]),
                 "auc": round(roc_auc_score(rg["y"], rg["p_model"]), 3)}]
    for column, name in BASELINES.items():
        policies.append({"name": name, "column": column, **tally(rg["y"], rg[column]), "auc": None})
    cheapest = min(policies[1:], key=lambda p: p["cost"])
    persistence_cost = policies[1]["cost"]
    headline = {
        "system_cost": policies[0]["cost"],
        "persistence_cost": persistence_cost,
        "pct_cheaper_than_persistence": round(100 * (1 - policies[0]["cost"] / persistence_cost), 1),
        "cheapest_baseline_on_test": cheapest["name"],
        "cheapest_baseline_cost": cheapest["cost"],
        # The honesty check: we must beat the CHEAPEST baseline, not only persistence
        "honesty_check_pass": policies[0]["cost"] < cheapest["cost"],
    }

    # ---- Onset: counties NOT in D2 today. This is the hard part ----
    on = rg[rg["cls"] < D2_CLASS]
    onset_rules = {name: tally(on["y"], on[col])["cost"] for col, name in BASELINES.items() if name != "Persistence"}
    best_rule = min(onset_rules, key=onset_rules.get)
    onset_tally = tally(on["y"], on["alarm_system"])
    onset = {
        "rows": len(on), "positives": int(on["y"].sum()),
        "system_cost": onset_tally["cost"], "best_rule": best_rule, "best_rule_cost": onset_rules[best_rule],
        "never_warn_cost": MISS_COST * int(on["y"].sum()),
        "precision": onset_tally["precision"], "recall": onset_tally["recall"],
        "auc": round(roc_auc_score(on["y"], on["p_model"]), 3),
    }

    # ---- Does the result depend on the cost we assumed? Try 2, 3, 5 and 10 ----
    # For each cost the system's threshold is picked again on VALIDATION rows.
    # The baselines keep their alarms, and we take the cheapest of them.
    vf = panel[val & focus]
    cost_sensitivity = []
    for cost in (2, 3, 5, 10):
        thr = pick_threshold(vf["p_model"], vf["y"], cost)
        cost_sensitivity.append({
            "miss_cost": cost,
            "system_cost": tally(rg["y"], rg["p_model"] >= thr, cost)["cost"],
            "best_baseline_cost": min(tally(rg["y"], rg[col], cost)["cost"] for col in BASELINES),
        })

    # ---- Year by year on the Rio Grande ----
    year_by_year = [{"year": int(year), "positives": int(g["y"].sum()),
                     "system_cost": tally(g["y"], g["alarm_system"])["cost"],
                     "persistence_cost": tally(g["y"], g["alarm_persistence"])["cost"]}
                    for year, g in rg.groupby(rg["date"].dt.year)]

    # ---- Transfer test: the same Rio Grande model on each river ----
    per_river = []
    for river in RIVERS:
        g = panel[test & (panel["river"] == river)]
        system = tally(g["y"], g["alarm_system"])
        rules = {name: tally(g["y"], g[col])["cost"] for col, name in BASELINES.items()}
        best = min(rules, key=rules.get)
        per_river.append({
            "river": river, "counties": g["fips"].nunique(),
            "system_cost": system["cost"], "persistence_cost": rules["Persistence"],
            "best_rule": best, "best_rule_cost": rules[best],
            "pct_cheaper_than_best_rule": round(100 * (1 - system["cost"] / rules[best]), 1),
            "own_river_cost": tally(g["y"], g["alarm_own_river"])["cost"],
            "all_rivers_cost": tally(g["y"], g["alarm_all_rivers"])["cost"],
            "precision": system["precision"], "recall": system["recall"],
            "auc": round(roc_auc_score(g["y"], g["p_model"]), 3),
        })

    results = {
        "threshold": threshold,
        # Costs on the VALIDATION years, where the threshold was picked (for reports/decision.md)
        "validation": {"Our system": tally(vf["y"], vf["alarm_system"])["cost"],
                       **{name: tally(vf["y"], vf[col])["cost"] for col, name in BASELINES.items()}},
        "rows": {"train": int((train & focus).sum()), "val": int((val & focus).sum()),
                 "test_focus": len(rg), "test_all": int(test.sum())},
        "policies": policies, "headline": headline, "onset": onset,
        "events": events(rg, "alarm_system"),
        "cost_sensitivity": cost_sensitivity, "year_by_year": year_by_year, "per_river": per_river,
        "logistic_cost": tally(rg["y"], rg["alarm_logistic"])["cost"],
        "shuffled_auc_mean": round(shuffled_auc(panel, train & focus, test & focus), 3),
        "feature_importance": [{"feature": f, "importance": round(float(i), 4)} for f, i in
                               sorted(zip(FEATURES_H, model.feature_importances_), key=lambda x: -x[1])],
    }
    return panel, results


if __name__ == "__main__":
    # Print every result as a plain table
    _, r = run_alert()
    table = lambda rows: print(pd.DataFrame(rows).to_string(index=False), "\n")
    print("Alarm threshold (picked on Rio Grande validation years):", r["threshold"])
    print("Rio Grande rows:", r["rows"])
    print("Costs on the validation years 2015-2018:", r["validation"], "\n")
    print("=== Rio Grande, test years: our system against the baselines (lower cost is better) ===")
    table(r["policies"])
    print("Headline:", r["headline"])
    print("Logistic regression cost, for comparison:", r["logistic_cost"], "\n")
    print("=== Onset rows (county not in D2 today) ===\n", r["onset"], "\n")
    print("=== Onset events (entered D2 after 8+ weeks out) ===\n", r["events"], "\n")
    print("=== Other miss costs ===")
    table(r["cost_sensitivity"])
    print("=== Year by year, Rio Grande (the last year is partial) ===")
    table(r["year_by_year"])
    print("=== Transfer test: the Rio Grande model on each river ===")
    table(r["per_river"])
    print("Shuffled-label AUC (should be near 0.5):", r["shuffled_auc_mean"], "\n")
    print("=== Inputs the forest relies on most ===")
    table(r["feature_importance"][:8])
