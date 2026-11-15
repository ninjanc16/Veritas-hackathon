"""seepage_calibration.py: fit the seepage model to the districts' published losses, and test it.

ADDED in round 3 (ARCHITECTURE.md sections 4.3 and 4.4). The definitions were fixed in
reports/decision.md on Nov 15, 2026 BEFORE this file was run on real data, and are not changed
after a result is seen. Nothing here feeds the sealant plan or the website yet.

Note: this "calibration" is about canal leakage. prob_calibration.py (forecast probabilities)
is a different thing with a similar name.

WHAT IS COMPARED WITH WHAT
  The target: each district's water LOSS in the 1998 Texas A&M table,
      Loss = authorised water x (1 - efficiency / 100)     (app/reference/districts.csv)
  These are 1998 ESTIMATES on water rights, not measured diversions, and the loss includes
  evaporation and spills as well as seepage.

  Four ways to say how much a district's canals leak, each summed over the SAME segments:
      raw = sum of  rate x length (ft) x width (ft) x (1 - lined share) x 273 days / 325,851
    M1       rate = permeability x 2.1205 x water-table factor      (the primary model)
    M2       rate = permeability x 2.1205                           (no water-table factor)
    texture  rate = the 1946 texture-table value                    (rival)
    length   rate = 1 for every segment                             (rival: canal length alone)
  Width is the middle of the segment's class range and the lined share is 0.3 everywhere: both
  are ASSUMPTIONS (config.py). The lined share is the same constant for every district, so it
  only shifts the fitted factor and changes no comparison.

  Each of the four gets ONE fitted factor c:  ln c = mean over districts of ln(Loss / raw).
  So c x raw matches the losses on average in log terms (the geometric mean of the ratio is 1).
  The SUM of calibrated seepage need not equal the sum of the losses.

THE TEST (leave one district out)
  For each district: fit c on the other districts, predict this one as c x raw, and record the
  absolute percent error. A model is judged by its median error over the held-out districts and
  by the rank correlation between its predictions and the losses.
  PASS RULE: a bootstrap over districts (10,000 draws, seed 0) of
      (rival's median error - M1's median error)
  must lie entirely above zero against the length rival. Otherwise the model did not beat canal
  length, and the volumes are not reliable. (The statistic is the difference of the two medians,
  recomputed on each resample; it is not the median of the per-district differences.)

THE SEGMENT SET, the same for all four: segments that are fundable (canal_class.fundable), lie
inside a district matched in the crosswalk, and have BOTH a permeability and a 1946 texture
rate. (758 segments have a permeability but no texture rate; they are left out here so that
every model is compared on identical segments.)

Run it with:  PYTHONPATH=src python -m farmdrought.seepage_calibration
              (writes reports/frozen/round3/seepage_calibration.json once; --force to replace)
"""
import json
import re
import sys
from datetime import datetime

import numpy as np
import pandas as pd

from farmdrought.canal_class import class_source, classify, fundable, match_segments, segment_name
from farmdrought.config import (CANAL_KSAT_CSV, CANAL_SOIL_CSV, CANAL_WIDTH_FT, CANALS_CSV, CANALS_GEOJSON, DISTRICTS_GEOJSON,
                                FEET_PER_KM, FROZEN, GALLONS_PER_ACRE_FOOT, LINED_SHARE, MANIFEST, MIN_DISTRICT_CANAL_KM,
                                ROOT, SEEPAGE_GAL_SQFT_DAY, SEEPAGE_SEASON_DAYS)
from farmdrought.districts import assign_districts, load_districts
from farmdrought.leaks import seepage_rate
from farmdrought.manifest import sha256_of

REFERENCE = ROOT / "app" / "reference"
DISTRICT_TABLE = REFERENCE / "districts.csv"
CROSSWALK = REFERENCE / "district_crosswalk.csv"
OSM_CANALS = ROOT / "app" / "data" / "osm_canals.json"
OUTPUT = "seepage_calibration.json"
MODELS = ["M1", "M2", "texture", "length"]
DRAWS, SEED = 10000, 0
DECLARED_IN = ('reports/decision.md, sections "Evaluation round 3" (physical model, declared at the same time), '
               '"Physical model: choices fixed on Nov 15, 2026 after the soil download and before any calibration or '
               'held-out test was run", and its paragraph "Canal classes, fixed on Nov 15, 2026 before any fit"')
PASS_SENTENCE = "Held-out districts: median error {error:.0%} (interval {lo:.0%} to {hi:.0%}), better than canal length alone."
FAIL_SENTENCE = ("The model did not predict held-out district losses better than canal length. Volumes are not "
                 "reliable; only the ranking order is shown.")
# How a 1998 abbreviation is spelled in the district map. Only these four are expanded.
ABBREVIATIONS = {"ccid": "cameron county irrigation district", "hcid": "hidalgo county irrigation district",
                 "hccid": "hidalgo & cameron counties irrigation district", "hcwcid": "hidalgo county wcid"}


# ---------------------------------------------------------------------------------------------
# The target, and the crosswalk between the two sets of district names
# ---------------------------------------------------------------------------------------------
def district_losses(table):
    """Loss = authorised water x (1 - efficiency / 100), for the rows that have both numbers.

    table : the 1998 table (district, efficiency_pct, authorized_af). Returns it with loss_af,
    without the rows that lack either number.
    """
    table = table.dropna(subset=["authorized_af", "efficiency_pct"]).copy()
    table["loss_af"] = table["authorized_af"] * (1 - table["efficiency_pct"] / 100)
    return table[["district", "authorized_af", "efficiency_pct", "loss_af"]].reset_index(drop=True)


def tidy(name):
    """Lower case, punctuation (except &) turned into spaces, "No." and "Number" dropped."""
    name = re.sub(r"\bno\b\.?|\bnumber\b", " ", name.lower())
    return " ".join(re.sub(r"[^a-z0-9& ]", " ", name).split())


def candidate_names(name):
    """The spellings a 1998 name may take in the district map. No guessing: only
      - the name itself, tidied;
      - an abbreviation such as "CCID#2 (San Benito)" spelled out, "cameron county irrigation
        district 2" (the town in brackets is dropped);
      - the plain name followed by "irrigation district", used as the START of a map name
        ("Delta Lake" -> "delta lake irrigation district ...").
    Returns (names that must match a map name exactly, a prefix a map name may start with).
    """
    plain = tidy(re.sub(r"\(.*?\)", " ", name))
    exact = [tidy(name), plain]
    short = re.fullmatch(r"([a-z]+) ?(\d+)", plain)
    if short and short.group(1) in ABBREVIATIONS:
        exact.append(f"{ABBREVIATIONS[short.group(1)]} {short.group(2)}")
    return exact, plain + " irrigation district"


def build_crosswalk(reference_names, map_names):
    """One row per 1998 district: the map district it is, and how it was matched.

    match = "exact" (the same text), "normalised" (the same after tidying, spelling out an
    abbreviation, or as the start of the map name; exactly one map name must fit) or "none".
    Unmatched districts are left out of the fit and listed. A human must check this table.
    """
    tidy_map = {name: tidy(name) for name in map_names}
    rows = []
    for name in reference_names:
        exact, prefix = candidate_names(name)
        if name in tidy_map:
            rows.append({"district": name, "map_district": name, "match": "exact"})
            continue
        fits = [m for m, t in tidy_map.items() if t in exact or t == prefix or t.startswith(prefix + " ")]
        rows.append({"district": name, "map_district": fits[0] if len(fits) == 1 else "",
                     "match": "normalised" if len(fits) == 1 else "none"})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# The segments
# ---------------------------------------------------------------------------------------------
def segment_table():
    """One row per mapped canal segment with everything the models need: district, class,
    fundable, permeability, water-table depth and the 1946 texture rate."""
    canals = pd.read_csv(CANALS_CSV, dtype={"fips": str, "id": str, "name": str}).fillna({"name": ""})
    with open(CANALS_GEOJSON) as f:
        lines = [feature["geometry"]["coordinates"] for feature in json.load(f)["features"]]
    assert len(lines) == len(canals), "the map file and the canal table must hold the same segments"
    ways = json.loads(OSM_CANALS.read_text(encoding="utf-8"))["ways"]
    matches = match_segments(lines, ways)
    canals["usgs_name"] = canals["name"]
    canals["name"] = [segment_name(name, match) for name, match in zip(canals["usgs_name"], matches)]
    canals["kind"] = [match["kind"] for match in matches]
    canals["piped_share"] = [match["piped_share"] for match in matches]
    rows = canals.to_dict("records")
    canals["class"] = [classify(row) for row in rows]
    canals["class_source"] = [class_source(row) for row in rows]
    canals["fundable"] = [fundable(row) for row in rows]

    soil = pd.read_csv(CANAL_SOIL_CSV, dtype={"id": str})
    ksat = pd.read_csv(CANAL_KSAT_CSV, dtype={"id": str})
    assert (soil["id"] == canals["id"]).all() and (ksat["id"] == canals["id"]).all(), "the soil files must follow the canal table"
    canals["texture_rate"] = soil["soil"].map(SEEPAGE_GAL_SQFT_DAY).to_numpy()
    canals["ksat_typ"], canals["wt_cm"] = ksat["ksat_typ"].to_numpy(), ksat["wt_cm"].to_numpy()

    # The district of each segment, exactly as districts.py assigns it for the sealant plan.
    canals["district"] = assign_districts(canals, load_districts())
    km_in = canals.groupby("district")["length_km"].sum()
    canals.loc[canals["district"].map(km_in) < MIN_DISTRICT_CANAL_KM, "district"] = ""
    return canals


def model_set(segments, crosswalk):
    """The segments every model is summed over, and what was kept and dropped per district.

    Kept: fundable, inside a district matched in the crosswalk, with a permeability AND a 1946
    texture rate. Returns (kept segments with the 1998 district name in "reference_district",
    a table per matched district of segments and km kept and dropped, with the reasons).
    """
    matched = crosswalk[crosswalk["match"] != "none"].set_index("map_district")["district"]
    inside = segments[segments["district"].isin(matched.index)].copy()
    inside["reference_district"] = inside["district"].map(matched)
    no_ksat, no_texture = inside["ksat_typ"].isna(), inside["texture_rate"].isna()
    keep = inside["fundable"] & ~no_ksat & ~no_texture
    summary = pd.DataFrame({
        "segments": inside.groupby("reference_district").size(),
        "km": inside.groupby("reference_district")["length_km"].sum(),
        "kept_segments": keep.groupby(inside["reference_district"]).sum(),
        "kept_km": inside["length_km"].where(keep, 0).groupby(inside["reference_district"]).sum(),
        "dropped_not_fundable": (~inside["fundable"]).groupby(inside["reference_district"]).sum(),
        "dropped_no_permeability": (inside["fundable"] & no_ksat).groupby(inside["reference_district"]).sum(),
        "dropped_no_texture_rate": (inside["fundable"] & ~no_ksat & no_texture).groupby(inside["reference_district"]).sum(),
    })
    summary["dropped_segments"] = summary["segments"] - summary["kept_segments"]
    summary["dropped_km"] = summary["km"] - summary["kept_km"]
    return inside[keep], summary


def raw_seepage(kept):
    """Raw modelled seepage per district, acre-feet per 273-day season, for the four models.

    kept : the segments from model_set. Every model is summed over exactly these rows.
    """
    width = kept["class"].map(lambda name: CANAL_WIDTH_FT[name][1])
    volume = kept["length_km"] * FEET_PER_KM * width * (1 - LINED_SHARE[1]) * SEEPAGE_SEASON_DAYS / GALLONS_PER_ACRE_FOOT
    rates = {
        "M1": [seepage_rate(k, w, c=1) for k, w in zip(kept["ksat_typ"], kept["wt_cm"])],
        "M2": [seepage_rate(k, None, c=1) for k in kept["ksat_typ"]],
        "texture": kept["texture_rate"].to_numpy(),
        "length": np.ones(len(kept)),
    }
    return pd.DataFrame({model: (np.asarray(rate, dtype=float) * volume).groupby(kept["reference_district"]).sum()
                         for model, rate in rates.items()})


# ---------------------------------------------------------------------------------------------
# The fit and the held-out test
# ---------------------------------------------------------------------------------------------
def fit_factor(model_values, losses):
    """The one factor c that brings a model's raw values to the losses, on average in log terms.

    ln c = mean over districts of ln(Loss / raw);  sd = standard deviation of those log ratios
    (n - 1 in the denominator). Districts whose raw value or loss is zero, negative or missing
    cannot enter a logarithm: they are excluded and listed. Returns dict(c, sd, n, excluded).
    """
    model_values, losses = pd.Series(model_values, dtype=float), pd.Series(losses, dtype=float)
    usable = (model_values > 0) & (losses.reindex(model_values.index) > 0)
    ratios = np.log(losses.reindex(model_values.index)[usable] / model_values[usable])
    return {"c": float(np.exp(ratios.mean())) if len(ratios) else float("nan"),
            "sd": float(ratios.std(ddof=1)) if len(ratios) > 1 else float("nan"),
            "n": int(len(ratios)), "excluded": [str(name) for name in model_values.index[~usable]]}


def median_error_gap(rival_errors, model_errors, draws=DRAWS, seed=SEED):
    """Bootstrap over districts of (rival's median error - model's median error).

    The same resampled districts are used for both. Returns the gap on the real districts, the
    2.5 and 97.5 percentiles over the resamples, and "passes": True only when the whole interval
    is above zero (the rival's median error is higher, so the model is better).
    """
    rival, model = np.asarray(rival_errors, dtype=float), np.asarray(model_errors, dtype=float)
    picked = np.random.default_rng(seed).integers(0, len(model), size=(draws, len(model)))
    gaps = np.median(rival[picked], axis=1) - np.median(model[picked], axis=1)
    lo, hi = np.percentile(gaps, [2.5, 97.5])
    return {"gap": float(np.median(rival) - np.median(model)), "lo": float(lo), "hi": float(hi),
            "passes": bool(lo > 0), "n_districts": int(len(model)), "draws": int(draws), "seed": int(seed)}


def leave_one_out(table, draws=DRAWS, seed=SEED):
    """The held-out test. table: one row per district, with "loss_af" and one column per model.

    For each district the factor is fitted on the OTHER districts and the district is predicted
    as c x its raw value. Returns, per model, every district's prediction and absolute percent
    error, the median error and the rank correlation between predictions and losses; then the
    bootstrap gaps, with the pass test (M1 against the length rival) named as such.
    """
    districts = list(table.index)
    losses = table["loss_af"]
    models = {}
    for model in [name for name in MODELS if name in table.columns]:
        predicted = pd.Series({d: fit_factor(table[model].drop(d), losses.drop(d))["c"] * table.loc[d, model]
                               for d in districts})
        errors = (predicted - losses).abs() / losses
        models[model] = {"predicted_af": {d: float(predicted[d]) for d in districts},
                         "abs_pct_error": {d: float(errors[d]) for d in districts},
                         "median_abs_pct_error": float(errors.median()),
                         "rank_correlation": float(predicted.corr(losses, method="spearman"))}
    errors_of = lambda model: [models[model]["abs_pct_error"][d] for d in districts]
    gaps = {f"{rival}_minus_{model}": median_error_gap(errors_of(rival), errors_of(model), draws, seed)
            for model in ("M1", "M2") for rival in ("length", "texture") if model in models and rival in models}
    picked = np.random.default_rng(seed).integers(0, len(districts), size=(draws, len(districts)))
    m1_medians = np.median(np.asarray(errors_of("M1"))[picked], axis=1)
    return {"districts": districts, "n_districts": len(districts), "models": models, "gaps": gaps,
            "pass_test": "length_minus_M1",
            "m1_median_error_interval": [float(v) for v in np.percentile(m1_medians, [2.5, 97.5])]}


def calibration_item(losses, crosswalk, segments):
    """The content of seepage_calibration.json (without its header)."""
    kept, summary = model_set(segments, crosswalk)
    table = raw_seepage(kept).join(losses.set_index("district")[["loss_af", "authorized_af"]], how="inner")
    no_segments = sorted(set(crosswalk.loc[crosswalk["match"] != "none", "district"]) & set(losses["district"]) - set(table.index))
    # Counts are for the districts that are really fitted. A matched district with no loss in the
    # 1998 table has segments in the set but enters no fit, so it is counted apart.
    fitted = kept[kept["reference_district"].isin(table.index)]
    not_fitted = kept[~kept["reference_district"].isin(table.index)]
    fits = {model: fit_factor(table[model], table["loss_af"]) for model in MODELS}
    held_out = leave_one_out(table)
    gap = held_out["gaps"]["length_minus_M1"]
    lo, hi = held_out["m1_median_error_interval"]
    calibrated = fits["M1"]["c"] * table["M1"]
    share = calibrated / table["authorized_af"]
    return {
        "what": "One factor per model fitted to the districts' 1998 loss estimates, and a leave-one-district-out "
                "test of the permeability model against canal length alone and the 1946 texture table. Every "
                "volume is MODELLED, not measured.",
        "target": "Loss = authorised water x (1 - efficiency / 100) from app/reference/districts.csv: 1998 estimates "
                  "on water rights, not measured diversions; the loss includes evaporation and spills.",
        "assumptions": {"width_ft_by_class_low_middle_high": CANAL_WIDTH_FT, "width_used": "the middle of the class range",
                        "lined_share": LINED_SHARE[1], "lined_share_note": "the same constant for every district, so it "
                        "only shifts the fitted factor", "season_days": SEEPAGE_SEASON_DAYS,
                        "gradient": "hydraulic gradient of 1 and no silt layer on the canal bed",
                        "missing_water_table": "read as no water table found in the surveyed profile: factor 1"},
        "crosswalk": crosswalk.to_dict("records"),
        "districts_without_a_loss": sorted(set(crosswalk["district"]) - set(losses["district"])),
        "districts_unmatched": crosswalk.loc[crosswalk["match"] == "none", "district"].tolist(),
        "districts_matched_but_with_no_segment_in_the_set": no_segments,
        "segment_set": "fundable segments inside a matched district that have a permeability AND a 1946 texture "
                       "rate; the same segments for all four models",
        "segments_by_district": summary.reset_index().rename(columns={"reference_district": "district"}).to_dict("records"),
        "districts_fitted": int(len(table)),
        "segments_kept": int(len(fitted)), "km_kept": float(fitted["length_km"].sum()),
        "counts_cover": "the fitted districts only (those with a loss in the 1998 table)",
        "segments_in_matched_districts_with_no_loss": int(len(not_fitted)),
        "km_in_matched_districts_with_no_loss": float(not_fitted["length_km"].sum()),
        "class_counts_in_the_set": fitted["class"].value_counts().to_dict(),
        "feature_code_33601_in_the_set": int((fitted["fcode"] == 33601).sum()),
        "raw_af_by_district": table[MODELS + ["loss_af", "authorized_af"]].reset_index().rename(
            columns={"index": "district", "reference_district": "district"}).to_dict("records"),
        "fit_all_districts": fits,
        "held_out": held_out,
        "passes": gap["passes"],
        "sentence": (PASS_SENTENCE.format(error=held_out["models"]["M1"]["median_abs_pct_error"], lo=lo, hi=hi)
                     if gap["passes"] else FAIL_SENTENCE),
        "description_only": {
            "note": "Calibrated M1 seepage (c x raw, fitted on all districts) as a share of authorised water. "
                    "A description for the chart in ARCHITECTURE.md section 4.5, not a test.",
            "share_of_authorised_water": {d: float(share[d]) for d in table.index},
            "calibrated_af": {d: float(calibrated[d]) for d in table.index},
            "districts_above_their_own_loss": [d for d in table.index if calibrated[d] > table.loc[d, "loss_af"]],
            "sum_calibrated_af": float(calibrated.sum()), "sum_loss_af": float(table["loss_af"].sum()),
            "sum_note": "The factor matches the losses on average in log terms, so these two sums need not be equal.",
        },
    }


def main(force=False):
    from farmdrought.export import git_state
    from farmdrought.round3 import ROUND3, write_items

    if (ROUND3 / OUTPUT).exists() and not force:
        write_items({OUTPUT: None})   # raises: already scored
    losses = district_losses(pd.read_csv(DISTRICT_TABLE))
    with open(DISTRICTS_GEOJSON) as f:
        map_names = sorted(feature["properties"]["district"] for feature in json.load(f)["features"])
    crosswalk = build_crosswalk(pd.read_csv(DISTRICT_TABLE)["district"].tolist(), map_names)
    crosswalk.to_csv(CROSSWALK, index=False)
    with open(FROZEN / "metrics.json") as f:
        frozen = json.load(f)
    header = {"added": True, "declared_in": DECLARED_IN,
              "computed_at": datetime.now().astimezone().isoformat(timespec="seconds"), **git_state(),
              "frozen_v1_manifest_sha256": frozen["frozen"]["manifest_sha256"], "manifest_sha256_now": sha256_of(MANIFEST),
              "canal_ksat_csv_sha256": sha256_of(CANAL_KSAT_CSV), "district_crosswalk_csv_sha256": sha256_of(CROSSWALK),
              "draws": DRAWS, "seed": SEED}
    for path in write_items({OUTPUT: {**header, **calibration_item(losses, crosswalk, segment_table())}}, force=force):
        print("wrote", path.relative_to(ROOT))


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--force"]):
        sys.exit("usage: python -m farmdrought.seepage_calibration [--force]")
    main(force="--force" in sys.argv)
