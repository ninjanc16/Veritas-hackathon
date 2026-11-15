"""
contract.py - the ONLY door between the app and the data.

What it does (plain English, for the judges):
  The pipeline team hands us 4 files (3 tables + 1 JSON of results). This module
  1) lists exactly what columns/keys those files must have (the "contract"),
  2) checks a file against that list and reports problems in plain English,
  3) loads the real files if they exist and are valid.

The app never computes results itself - it only shows what is in these files.
"""
import datetime
import json
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Where the files live. Every path is built from the repo root, so it works
# no matter which folder the app is started from.
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_DIR = REPO_ROOT / "data" / "processed"        # real handoff tables (read only!)
REAL_METRICS = REPO_ROOT / "reports" / "metrics.json"  # real handoff results (read only!)
DEMO_DIR = REPO_ROOT / "app" / "demo_data"         # default folder for app/make_demo_data.py (a test helper)

CONTRACT_VERSION = 2

RIVERS = ["Rio Grande", "Mississippi", "Missouri", "Colorado", "Ohio"]
TIERS = ["Low", "Watch", "Warning"]

# ---------------------------------------------------------------------------
# Column lists: (name, kind), in the exact order the contract requires.
# kinds: date, str, fips (5-char text), int, float, bool
# ---------------------------------------------------------------------------
PRED_COLUMNS = [
    ("date", "date"), ("fips", "fips"), ("county", "str"), ("state", "str"),
    ("river", "str"), ("lat", "float"), ("lon", "float"),
    ("y", "int"), ("cls", "int"), ("d2_streak", "int"),
    ("p_model", "float"), ("tier", "str"),
    ("alarm_system", "bool"), ("alarm_persistence", "bool"), ("alarm_d1_now", "bool"),
    ("alarm_worsening", "bool"), ("alarm_calendar", "bool"),
]

OUTLOOK_COLUMNS = [
    ("date", "date"), ("fips", "fips"), ("county", "str"), ("state", "str"),
    ("river", "str"), ("cls", "int"),
    ("y_season", "int"), ("p_season", "float"), ("alarm_season", "bool"),
    ("alarm_season_persistence", "bool"), ("alarm_season_d1", "bool"),
    ("p_season_usual", "float"),
    ("y_weeks", "int"), ("weeks_model", "float"), ("weeks_last_year", "float"),
    ("weeks_same_as_now", "float"), ("weeks_usual", "float"),
]

LATEST_COLUMNS = [
    ("date", "date"), ("fips", "fips"), ("county", "str"), ("state", "str"),
    ("river", "str"), ("lat", "float"), ("lon", "float"),
    ("cls", "int"), ("d2_streak", "int"), ("p_model", "float"), ("tier", "str"),
    ("alarm_system", "bool"), ("p_season", "float"), ("season_tier", "str"),
    ("weeks_model", "float"), ("weeks_usual", "float"),
]

# Extra columns the pipeline added to latest.parquet for the map (all optional, all together).
# If they are there, the app uses them; if not (older files), the map falls back to the tiers.
MAP_COLUMNS = ["risk_level", "weeks_low", "weeks_high", "typical_drought_weeks",
               "longest_drought_weeks", "damage_months", "damage_usd_per_100_head"]
# What metrics.json["map_fields"] must say when those columns are present (the app prints it).
MAP_FIELDS_KEYS = ["feed_cost_per_head_month", "feed_cost_source", "tested"]

# ---------------------------------------------------------------------------
# Optional pieces added by the "Canal action" pivot. Every one may be missing: the app
# then still opens and says "not available yet". When one IS there, we check its type.
# (name, kind) pairs, same kinds as above.
# ---------------------------------------------------------------------------
OPTIONAL_OUTLOOK_COLUMNS = [("p_season_res", "float")]
OPTIONAL_LATEST_COLUMNS = [("p_season_res", "float"), ("d2_share_history", "float"),
                           ("res_name", "str"), ("res_pct_full", "float")]
RESERVOIR_NAMES = ["Amistad-Falcon", "Elephant Butte", "none"]   # allowed values of res_name
# Optional keys of metrics.json and the sub-keys each must have when present.
OPTIONAL_METRICS_KEYS = {
    "trigger": ["issue_months", "threshold", "rows", "drought_seasons", "rules", "value_sweep",
                "forecast_beats_d1_rule", "reservoir_forecast_beats_d1_rule"],
    "reservoir": ["systems", "counties_without_reservoir", "note"],
    "losses": ["source", "years", "causes_included", "total_usd", "by_year", "by_county", "note"],
    # Canal map (the lines themselves are in data/processed/canals.geojson, read by app/mapdata.py).
    "canals": ["source", "total_km", "segments", "by_county", "note"],
    "canal_priority": ["levels", "by_level", "by_soil", "by_county", "named", "note"],
    # The pipeline's sealant plan for Texas irrigation districts (budget shared by seepage and forecast).
    "districts": ["source", "budget_usd", "assumptions", "rule", "n_districts", "districts", "note"],
}

# ---------------------------------------------------------------------------
# metrics.json: every key the contract requires. A dotted name like
# "season.focus" means "the key 'focus' inside the key 'season'".
# ---------------------------------------------------------------------------
METRICS_KEYS = [
    "contract_version", "generated_at", "is_final", "focus_river", "training_scope",
    "n_rows", "n_focus_rows", "n_counties", "n_focus_counties", "horizon_weeks",
    "train_years", "val_years", "test_years", "latest_week", "miss_cost",
    "policies", "headline", "onset", "events", "cost_sensitivity", "year_by_year",
    "per_river", "season", "year", "failure_examples", "shuffled_auc_mean",
    "ablations", "feature_importance", "limits",
]
# Keys we check one level deeper (the ones the app actually reads).
METRICS_NESTED_KEYS = {
    "headline": ["system_cost", "persistence_cost", "pct_cheaper_than_persistence",
                 "cheapest_baseline_on_test", "cheapest_baseline_cost", "honesty_check_pass"],
    "onset": ["rows", "positives", "system_cost", "best_rule", "best_rule_cost",
              "never_warn_cost", "precision", "recall", "auc"],
    "season": ["horizon_weeks", "target", "test_years", "threshold", "focus", "per_river"],
    "season.focus": ["rows", "base_rate", "precision", "recall", "auc", "system_cost",
                     "persistence_cost", "d1_rule_cost", "usual_cost", "always_warn_cost",
                     "never_warn_cost", "pct_cheaper_than_persistence",
                     "beats_every_baseline", "years_better_than_usual"],
    "year": ["horizon_weeks", "target", "test_years", "focus", "per_river"],
    "year.focus": ["rows", "mean_weeks", "mae_system", "mae_same_as_now", "mae_last_year",
                   "mae_usual", "beats_every_baseline", "years_better_than_last_year",
                   "years_better_than_usual"],
}


# ---------------------------------------------------------------------------
# Small helpers used by the validators
# ---------------------------------------------------------------------------
def _type_ok(series, kind):
    """True if a pandas column has the type the contract asks for."""
    if kind == "date":
        # A parquet DATE column reads back as plain Python dates (object); a timestamp
        # column reads back as datetime64. Both are real dates. Text like "2026-01-06" is not.
        if pd.api.types.is_datetime64_any_dtype(series):
            return True
        return series.dtype == object and all(isinstance(v, datetime.date) for v in series.dropna())
    if kind in ("str", "fips"):
        return pd.api.types.is_string_dtype(series)
    if kind == "int":
        return pd.api.types.is_integer_dtype(series)
    if kind == "float":
        return pd.api.types.is_float_dtype(series)
    if kind == "bool":
        return pd.api.types.is_bool_dtype(series)
    return False


def _check_frame(df, spec, name):
    """Check column names, order, types and missing values. Returns a list of problems."""
    problems = []
    wanted = [col for col, _ in spec]

    # 1) Every required column must be there.
    missing = [c for c in wanted if c not in df.columns]
    if missing:
        return [f"{name}: missing columns {missing}"]

    # 2) Required columns must come first, in order. Extra columns at the END are fine.
    if list(df.columns[: len(wanted)]) != wanted:
        problems.append(f"{name}: columns are not in the contract order")

    # 3) Each column must have the right type and no empty cells.
    for col, kind in spec:
        if not _type_ok(df[col], kind):
            problems.append(f"{name}: column '{col}' should be {kind}, got {df[col].dtype}")
        if df[col].isna().any():
            problems.append(f"{name}: column '{col}' has missing values")
    return problems


def _check_sorted(df, sort_cols, name):
    """The contract says rows are sorted. Check that."""
    ordered = df.sort_values(sort_cols, kind="stable")
    if not (ordered.index == df.index).all():
        return [f"{name}: rows are not sorted by {sort_cols}"]
    return []


def _check_range(df, col, low, high, name):
    """Every value in df[col] must be between low and high."""
    if col in df.columns and not df[col].between(low, high).all():
        return [f"{name}: column '{col}' has values outside {low} to {high}"]
    return []


def _check_in(df, col, allowed, name):
    """Every value in df[col] must be one of the allowed values."""
    if col in df.columns and not df[col].isin(allowed).all():
        return [f"{name}: column '{col}' has values not in {allowed}"]
    return []


def _check_fips(df, name):
    """County codes must be text of exactly 5 digits (leading zeros kept)."""
    ok = df["fips"].str.len().eq(5) & df["fips"].str.isdigit()
    return [] if ok.all() else [f"{name}: 'fips' must be 5-digit text"]


# ---------------------------------------------------------------------------
# The four validators. Each returns a list of problems. Empty list = valid.
# ---------------------------------------------------------------------------
def validate_predictions(df):
    name = "predictions"
    problems = _check_frame(df, PRED_COLUMNS, name)
    if problems:
        return problems  # no point checking values if the shape is wrong
    problems += _check_sorted(df, ["date", "fips"], name)
    problems += _check_fips(df, name)
    problems += _check_in(df, "river", RIVERS, name)
    problems += _check_in(df, "tier", TIERS, name)
    problems += _check_in(df, "y", [0, 1], name)
    problems += _check_range(df, "cls", 0, 5, name)
    problems += _check_range(df, "p_model", 0, 1, name)
    return problems


def validate_outlook(df):
    name = "outlook"
    problems = _check_frame(df, OUTLOOK_COLUMNS, name)
    if problems:
        return problems
    problems += _check_sorted(df, ["date", "fips"], name)
    problems += _check_fips(df, name)
    problems += _check_in(df, "river", RIVERS, name)
    problems += _check_in(df, "y_season", [0, 1], name)
    problems += _check_range(df, "cls", 0, 5, name)
    problems += _check_range(df, "y_weeks", 0, 52, name)
    for col in ("p_season", "p_season_usual"):
        problems += _check_range(df, col, 0, 1, name)
    problems += _check_optional_columns(df, OPTIONAL_OUTLOOK_COLUMNS, name)
    problems += _check_range(df, "p_season_res", 0, 1, name)
    return problems


def has_map_fields(df):
    """True when latest.parquet carries all the optional map columns."""
    return all(c in df.columns for c in MAP_COLUMNS)


def _check_map_columns(df, name):
    """The optional map columns: all or nothing, and sensible values."""
    present = [c for c in MAP_COLUMNS if c in df.columns]
    if not present:
        return []
    if len(present) < len(MAP_COLUMNS):
        return [f"{name}: map columns are incomplete, missing {[c for c in MAP_COLUMNS if c not in present]}"]
    problems = []
    for col in MAP_COLUMNS:
        if df[col].isna().any():
            problems.append(f"{name}: column '{col}' has missing values")
    problems += _check_in(df, "risk_level", TIERS, name)
    for col in ("weeks_low", "weeks_high"):
        problems += _check_range(df, col, 0, 52, name)
    if (df["weeks_low"] > df["weeks_high"]).any():
        problems.append(f"{name}: 'weeks_low' is above 'weeks_high' for some counties")
    for col in ("typical_drought_weeks", "longest_drought_weeks", "damage_months", "damage_usd_per_100_head"):
        if (df[col] < 0).any():
            problems.append(f"{name}: column '{col}' has negative values")
    return problems


def _check_optional_columns(df, spec, name):
    """Optional columns: fine when absent; when present they need the right type and no gaps."""
    problems = []
    for col, kind in spec:
        if col not in df.columns:
            continue
        if not _type_ok(df[col], kind):
            problems.append(f"{name}: optional column '{col}' should be {kind}, got {df[col].dtype}")
        if df[col].isna().any():
            problems.append(f"{name}: optional column '{col}' has missing values")
    return problems


def _check_pivot_latest(df, name):
    """Checks for the optional canal-pivot columns of latest.parquet."""
    problems = _check_optional_columns(df, OPTIONAL_LATEST_COLUMNS, name)
    for col in ("p_season_res", "d2_share_history"):
        problems += _check_range(df, col, 0, 1, name)
    problems += _check_in(df, "res_name", RESERVOIR_NAMES, name)
    if "res_pct_full" in df.columns and "res_name" in df.columns:
        # -1 means "no reservoir"; otherwise a percent from 0 to 100.
        none = df["res_name"] == "none"
        if not (df.loc[none, "res_pct_full"] == -1).all():
            problems.append(f"{name}: 'res_pct_full' must be -1 when 'res_name' is 'none'")
        if not df.loc[~none, "res_pct_full"].between(0, 100).all():
            problems.append(f"{name}: 'res_pct_full' must be 0 to 100 for a real reservoir")
    return problems


def validate_latest(df):
    name = "latest"
    problems = _check_frame(df, LATEST_COLUMNS, name)
    if problems:
        return problems
    problems += _check_sorted(df, ["fips"], name)
    problems += _check_fips(df, name)
    problems += _check_in(df, "river", RIVERS, name)
    problems += _check_in(df, "tier", TIERS, name)
    problems += _check_in(df, "season_tier", TIERS, name)
    problems += _check_range(df, "cls", 0, 5, name)
    for col in ("p_model", "p_season"):
        problems += _check_range(df, col, 0, 1, name)
    problems += _check_map_columns(df, name)
    problems += _check_pivot_latest(df, name)
    return problems


def _dig(d, dotted):
    """Follow a dotted path like 'season.focus' into nested dicts. None if not found."""
    for part in dotted.split("."):
        if not isinstance(d, dict) or part not in d:
            return None
        d = d[part]
    return d


def validate_metrics(d, n_rows=None):
    """Check metrics.json. If n_rows is given, it must match the predictions length."""
    problems = []
    for key in METRICS_KEYS:
        if key not in d:
            problems.append(f"metrics: missing key '{key}'")
    for parent, children in METRICS_NESTED_KEYS.items():
        block = _dig(d, parent)
        if block is None:
            continue  # already reported above (or the parent is missing)
        for child in children:
            if child not in block:
                problems.append(f"metrics: missing key '{parent}.{child}'")
    # Optional blocks (trigger / reservoir / losses): absent is fine, present must be complete.
    for parent, children in OPTIONAL_METRICS_KEYS.items():
        if parent not in d:
            continue
        if not isinstance(d[parent], dict):
            problems.append(f"metrics: '{parent}' should be an object")
            continue
        problems += [f"metrics: missing key '{parent}.{c}'" for c in children if c not in d[parent]]
    if d.get("contract_version") != CONTRACT_VERSION:
        problems.append(f"metrics: contract_version must be {CONTRACT_VERSION}")
    if n_rows is not None and d.get("n_rows") != n_rows:
        problems.append(f"metrics: n_rows is {d.get('n_rows')} but predictions has {n_rows} rows")
    return problems


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def _read(pred_path, outlook_path, latest_path, metrics_path):
    """Read the four files from the given paths. Dates come back as dates."""
    pred = pd.read_parquet(pred_path)
    outlook = pd.read_parquet(outlook_path)
    latest = pd.read_parquet(latest_path)
    with open(metrics_path, encoding="utf-8") as f:
        metrics = json.load(f)
    return pred, outlook, latest, metrics


def _paths(folder, metrics_path):
    return (folder / "predictions.parquet", folder / "outlook.parquet",
            folder / "latest.parquet", metrics_path)


def _datetime_dates(pred, outlook, latest):
    """Turn every 'date' column into pandas datetimes, so the app can use .dt.year etc."""
    return tuple(df.assign(date=pd.to_datetime(df["date"])) for df in (pred, outlook, latest))


def validate_all(pred, outlook, latest, metrics):
    """Run all four validators and return one combined list of problems."""
    problems = (validate_predictions(pred) + validate_outlook(outlook)
                + validate_latest(latest) + validate_metrics(metrics, n_rows=len(pred)))
    # If the map columns are there, metrics.json must explain them (the app prints that text).
    if has_map_fields(latest):
        block = metrics.get("map_fields")
        if not isinstance(block, dict):
            problems.append("metrics: missing key 'map_fields' (needed because latest has the map columns)")
        else:
            problems += [f"metrics: missing key 'map_fields.{k}'" for k in MAP_FIELDS_KEYS if k not in block]
    return problems


def load():
    """
    Returns (predictions, outlook, latest, metrics, source, problems).

      source   = "real" when all four real files exist AND are valid, otherwise "none".
      problems = [] normally. If real files are missing or broken, it lists what is wrong
                 and the four tables are None (we never edit or patch the real files).

    This function never writes any file.
    """
    real_paths = _paths(REAL_DIR, REAL_METRICS)

    # No real files -> nothing to show, and say which ones are missing.
    missing = [p for p in real_paths if not p.exists()]
    if missing:
        return (None, None, None, None, "none", [f"missing real file: {p}" for p in missing])

    # Real files exist -> read and check them.
    try:
        real = _read(*real_paths)
        problems = validate_all(*real)
    except Exception as err:  # unreadable file, bad JSON, etc.
        real, problems = None, [f"could not read the real files: {err}"]

    if not problems:
        # Validated as-is first; only then convert the date columns for the app's use.
        return (*_datetime_dates(*real[:3]), real[3], "real", [])
    return (None, None, None, None, "none", problems)  # broken real files: no data + the problem list


# ---------------------------------------------------------------------------
# Fixed reference files for the "Canal action" tab (published figures, not handoff data)
# ---------------------------------------------------------------------------
REFERENCE_DIR = REPO_ROOT / "app" / "reference"


def load_reference():
    """Returns (districts DataFrame, costs dict) from app/reference/. Read only."""
    districts = pd.read_csv(REFERENCE_DIR / "districts.csv")
    with open(REFERENCE_DIR / "costs.json", encoding="utf-8") as f:
        costs = json.load(f)
    return districts, costs
