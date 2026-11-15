"""issues.py: turn today's data into a short list of things someone should act on.

Every issue comes from a plain rule over real data. Nothing here is a model, and nothing is
written by hand. Each issue says WHAT happened, WHERE, WHO should act, and which source and
date it rests on, so a reader can check it.

THE RULES (cut-offs marked "ours" are our own choices, not official ones):
  Critical
    1. A county ENTERED severe drought (D2 or worse) on this week's drought map.
    2. A reservoir system is lower than 90% of the same month in earlier years ("ours").
    3. The National Weather Service has a Severe or Extreme alert out for a river county.
  Important
    4. The 4-week alert is raised for a county that is not yet in severe drought.
    5. A county got one class worse on this week's drought map.
    6. An irrigation district is at Warning and the sealant plan pays for canals in it.
    7. A reservoir system is lower than 75% of the same month in earlier years ("ours").
    8. Any other National Weather Service alert for a river county.
  Context
    9. Counties at Warning where under 0.1 inch of rain is forecast for the next 7 days ("ours").
   10. Live river flow at the two USGS gauges on the Texas Rio Grande.

LIVE SOURCES (public, no key, checked Nov 14, 2026):
  National Weather Service  https://api.weather.gov   alerts, and the 7-day rain forecast
  USGS Water Data           https://api.waterdata.usgs.gov   river flow, every 15 minutes
The drought map, the reservoirs and the forecast come from files the refresh already saved.
If a live source cannot be reached, its issues are left out and that is written in the file.

Writes reports/issues.json. Run it with:  PYTHONPATH=src python -m farmdrought.issues
"""
import json
from datetime import datetime, timezone

import pandas as pd
import requests

from farmdrought.config import COUNTY_RESERVOIR, D2_CLASS, FOCUS_RIVER, LATEST, METRICS, REPORTS, SEASON_THRESHOLD
from farmdrought.drought import load_usdm
from farmdrought.reservoirs import load_reservoirs, reservoir_features

ISSUES_JSON = REPORTS / "issues.json"
# The weather service asks every program to name itself. This is a generic project name.
HEADERS = {"User-Agent": "rio-grande-drought-outlook (hackathon project)", "Accept": "application/geo+json"}
NWS = "https://api.weather.gov"
USGS = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/latest-continuous/items"
# The only two USGS gauges on the Texas Rio Grande that report live flow (both in Big Bend)
GAUGES = {"USGS-08374550": "Rio Grande near Castolon", "USGS-08375300": "Rio Grande at Rio Grande Village"}
DROUGHT_NAMES = ["no drought", "D0 abnormally dry", "D1 moderate", "D2 severe", "D3 extreme", "D4 exceptional"]
RESERVOIR_CRITICAL, RESERVOIR_IMPORTANT = 0.10, 0.25   # ours: rank against the same month in earlier years
DRY_WEEK_INCHES = 0.1                                  # ours: less rain than this in 7 days counts as "none"
MM_PER_INCH = 25.4
SEVERITIES = ["Critical", "Important", "Context"]


STATE_OF = {"08": "Colorado", "35": "New Mexico", "48": "Texas"}   # first two digits of a county code


def issue(severity, title, detail, who, where, source, as_of, rule, district=""):
    """One issue, always with the same fields.

    where    : the county codes (FIPS) it is about, so a map can jump there
    district : the irrigation district's name, for the sealing issues only
    """
    return {"severity": severity, "title": title, "detail": detail, "who": who, "where": where,
            "states": sorted({STATE_OF[fips[:2]] for fips in where}), "district": district,
            "source": source, "as_of": str(as_of), "rule": rule}


def drought_map_issues(counties):
    """Rules 1 and 5: what changed on this week's drought map."""
    usdm = load_usdm()
    row = {fips: i for i, fips in enumerate(usdm["fips"])}
    week = usdm["dates"][-1].date()
    out = []
    for c in counties.itertuples():
        now, before = usdm["classes"][row[c.fips], -1], usdm["classes"][row[c.fips], -2]
        if pd.isna(now) or pd.isna(before) or now <= before:
            continue  # no data, or not worse than last week
        place = f"{c.county}, {c.state}"
        change = f"{DROUGHT_NAMES[int(before)]} last week, {DROUGHT_NAMES[int(now)]} this week"
        if now >= D2_CLASS > before:
            out.append(issue("Critical", f"{place} entered severe drought this week", change + ". D2 is the level "
                             "that starts the clock for federal drought aid to livestock producers.",
                             "Ranchers and the county Farm Service Agency office", [c.fips],
                             "U.S. Drought Monitor", week, 1))
        else:
            out.append(issue("Important", f"{place} got worse on the drought map this week", change + ".",
                             "County officials and producers", [c.fips], "U.S. Drought Monitor", week, 5))
    return out


def alert_issues(counties):
    """Rule 4: the 4-week alert is raised where severe drought has not arrived yet."""
    out = []
    for c in counties[counties["alarm_system"] & (counties["cls"] < D2_CLASS)].itertuples():
        out.append(issue("Important", f"4-week alert raised for {c.county}, {c.state}",
                         f"The county is at {DROUGHT_NAMES[c.cls]} now, and the 4-week forecast expects severe "
                         f"drought within 4 weeks (risk score {c.p_model:.2f}). The score is not a probability.",
                         "Ranchers: line up feed. Districts: check deliveries.", [c.fips],
                         "Our 4-week alert, on the latest drought map", c.date, 4))
    return out


def district_issues(metrics, counties):
    """Rule 6: districts at Warning that the sealant plan sends money to."""
    block = metrics["districts"]
    texas = counties[counties["state"] == "Texas"].set_index("county")["fips"]  # districts are Texas only
    out = []
    for d in block["districts"]:
        if d["risk"] != "Warning" or d["sealant_usd"] <= 0:
            continue
        first = f" Start with: {', '.join(d['first_canals'])}." if d["first_canals"] else ""
        out.append(issue("Important", f"{d['district']}: decide on sealing {d['sealed_km']} km of canal",
                         f"The 6-month outlook for its counties is {d['p_season']:.2f}, over the "
                         f"{SEASON_THRESHOLD} warning line. At a ${block['budget_usd']:,} budget for all districts, "
                         f"the plan puts ${d['sealant_usd']:,} here.{first} The plan assumes unlined canals, so "
                         "check lining on the ground first.",
                         "The district's board and manager", [texas[name] for name in d["counties"]],
                         "Our 6-month outlook, the USGS canal map, the USDA soil survey", metrics["latest_week"], 6,
                         district=d["district"]))
    return out


def reservoir_issues():
    """Rules 2 and 7: how low each reservoir system is for the time of year."""
    daily = load_reservoirs()
    out = []
    for name in daily.columns:
        pct = daily[name].dropna()
        day = pct.index[-1]
        rank = reservoir_features(pct, pd.DatetimeIndex([day]))["res_pctile"].iloc[0]  # 0 = lowest on record
        month_ago = pct.get(day - pd.Timedelta(days=30))
        change = "" if pd.isna(month_ago) else f" It moved {pct.iloc[-1] - month_ago:+.1f} points in 30 days."
        if rank >= RESERVOIR_IMPORTANT:
            continue
        n_counties = sum(1 for system in COUNTY_RESERVOIR.values() if system == name)
        out.append(issue("Critical" if rank < RESERVOIR_CRITICAL else "Important",
                         f"{name} reservoir storage is {pct.iloc[-1]:.1f}% full",
                         f"That is lower than {100 * (1 - rank):.0f}% of the same month in earlier years back to "
                         f"1990.{change} {n_counties} river counties draw from it.",
                         "The Rio Grande Watermaster and district managers",
                         [fips for fips, system in COUNTY_RESERVOIR.items() if system == name],
                         "Texas Water Development Board, Water Data for Texas", day.date(), 2 if rank < RESERVOIR_CRITICAL else 7))
    return out


def weather_alert_issues(counties):
    """Rules 3 and 8: National Weather Service alerts that are active right now."""
    names = {c.fips: f"{c.county}, {c.state}" for c in counties.itertuples()}
    states = {"Texas": "TX", "New Mexico": "NM", "Colorado": "CO"}
    out, seen = [], set()
    for state in sorted({states[s] for s in counties["state"]}):
        reply = requests.get(f"{NWS}/alerts/active", params={"area": state}, headers=HEADERS, timeout=60)
        reply.raise_for_status()
        for feature in reply.json()["features"]:
            p = feature["properties"]
            # the alert lists its counties as "SAME" codes: a 0 followed by the 5-digit county code
            hit = [code[1:] for code in p["geocode"].get("SAME", []) if code[1:] in names]
            if not hit or p["id"] in seen:
                continue
            seen.add(p["id"])
            severe = p["severity"] in ("Severe", "Extreme")
            out.append(issue("Critical" if severe else "Important",
                             f"{p['event']}: {', '.join(names[f] for f in hit)}",
                             (p["headline"] or p["event"]) + f" Weather service severity: {p['severity']}.",
                             "County officials and anyone working outdoors", hit,
                             "National Weather Service, active alerts", p["sent"][:16], 3 if severe else 8))
    return out


def rain_forecast_issue(counties):
    """Rule 9: Warning counties with no real rain in the 7-day forecast (one issue for all of them)."""
    warned = counties[counties["p_season"] >= SEASON_THRESHOLD]
    dry, checked, updated = [], 0, ""
    for c in warned.itertuples():
        try:
            # step 1: which forecast grid square is this county's center in?  step 2: that square's forecast
            point = requests.get(f"{NWS}/points/{c.lat:.4f},{c.lon:.4f}", headers=HEADERS, timeout=60).json()
            grid = requests.get(point["properties"]["forecastGridData"], headers=HEADERS, timeout=60).json()["properties"]
        except Exception:
            continue  # this county's forecast could not be read: leave it out
        checked += 1
        updated = max(updated, grid["updateTime"][:16])
        inches = sum(v["value"] or 0 for v in grid["quantitativePrecipitation"]["values"]) / MM_PER_INCH
        if inches < DRY_WEEK_INCHES:
            dry.append((c.fips, f"{c.county}, {c.state}"))
    if not dry:
        return []
    return [issue("Context", f"No real rain forecast this week for {len(dry)} of {checked} Warning counties",
                  f"Under {DRY_WEEK_INCHES} inch in the next 7 days at the county center: "
                  f"{', '.join(name for _, name in dry)}. A week's forecast says nothing about the season. "
                  "It only means no relief is on the way right now.",
                  "Everyone planning water for the next week", [fips for fips, _ in dry],
                  "National Weather Service, gridded 7-day forecast", updated, 9)]


def river_flow_issue():
    """Rule 10: live flow at the two Texas gauges (one context line)."""
    readings, newest = [], ""
    for gauge, name in GAUGES.items():
        reply = requests.get(USGS, params={"monitoring_location_id": gauge, "parameter_code": "00060", "f": "json"},
                             headers={"User-Agent": HEADERS["User-Agent"]}, timeout=60)
        reply.raise_for_status()
        features = reply.json().get("features", [])
        if features:
            p = features[0]["properties"]
            readings.append(f"{name}: {float(p['value']):,.0f} cubic feet per second")
            newest = max(newest, p["time"][:16])
    if not readings:
        return []
    return [issue("Context", "Live river flow in Big Bend", "; ".join(readings) + ". Both gauges are upstream of "
                  "the canal districts. Flow near the districts is measured by the boundary commission, which has "
                  "no open data service.", "Water allocators", ["48043"],
                  "USGS Water Data, provisional readings", newest, 10)]


def run_issues():
    """Apply every rule and write reports/issues.json. Returns the report."""
    latest = pd.read_parquet(LATEST)
    counties = latest[latest["river"] == FOCUS_RIVER]
    with open(METRICS) as f:
        metrics = json.load(f)

    issues, not_reached = [], []
    saved = [lambda: drought_map_issues(counties), lambda: alert_issues(counties),
             lambda: district_issues(metrics, counties), reservoir_issues]
    live = {"National Weather Service alerts": lambda: weather_alert_issues(counties),
            "National Weather Service rain forecast": lambda: rain_forecast_issue(counties),
            "USGS river flow": river_flow_issue}
    for rule in saved:
        issues += rule()
    for name, rule in live.items():
        try:
            issues += rule()
        except Exception as error:   # a live source is down: say so, and keep the rest
            not_reached.append(f"{name} ({str(error)[:120]})")

    issues.sort(key=lambda i: (SEVERITIES.index(i["severity"]), i["rule"], i["title"]))
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "drought_week": metrics["latest_week"],
        "counts": {s: sum(i["severity"] == s for i in issues) for s in SEVERITIES},
        "not_reached": not_reached,
        "note": "Each issue comes from a fixed rule over public data (the rules are listed at the top of "
                "src/farmdrought/issues.py). Cut-offs for reservoirs and rain are our own choices. Sealing issues "
                "assume unlined canals. An issue is a prompt to check, not a finding.",
        "issues": issues,
    }
    ISSUES_JSON.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    report = run_issues()
    print(report["counts"], "| not reached:", report["not_reached"] or "none", "\n")
    for i in report["issues"]:
        print(f"[{i['severity']}] {i['title']}\n    {i['detail']}\n    Who: {i['who']} | Source: {i['source']}, {i['as_of']}\n")
