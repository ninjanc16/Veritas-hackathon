"""Tests for the issues list: the rules must fire exactly when they say they do."""
import json

import pandas as pd

from farmdrought.issues import ISSUES_JSON, SEVERITIES, alert_issues, district_issues


def toy_counties():
    return pd.DataFrame({
        "fips": ["48215", "48061"], "county": ["Hidalgo", "Cameron"], "state": "Texas",
        "date": "2026-11-10", "cls": [2, 3], "p_model": [0.8, 0.9], "alarm_system": [True, True]})


def test_four_week_alert_issue_only_where_severe_drought_has_not_arrived():
    # Both counties have the alarm on. Cameron is already at D2 (class 3), so only Hidalgo is news.
    issues = alert_issues(toy_counties())
    assert [i["where"] for i in issues] == [["48215"]]
    assert issues[0]["severity"] == "Important" and issues[0]["states"] == ["Texas"]


def test_sealing_issue_needs_a_warning_and_money_in_the_plan():
    district = lambda name, risk, usd: {"district": name, "risk": risk, "sealant_usd": usd, "sealed_km": 1.0,
                                        "p_season": 0.3, "first_canals": [], "counties": ["Hidalgo"]}
    metrics = {"latest_week": "2026-11-10", "districts": {"budget_usd": 100000, "districts": [
        district("A", "Warning", 500), district("B", "Watch", 500), district("C", "Warning", 0)]}}
    issues = district_issues(metrics, toy_counties())
    assert [i["district"] for i in issues] == ["A"]      # B is not at Warning, C gets no money
    assert issues[0]["where"] == ["48215"]


def test_saved_issue_file_is_well_formed():
    report = json.loads(ISSUES_JSON.read_text())
    issues = report["issues"]
    assert all(i["severity"] in SEVERITIES for i in issues)
    # worst first, and every issue names who acts, its source and the date it rests on
    order = [SEVERITIES.index(i["severity"]) for i in issues]
    assert order == sorted(order)
    assert all(i["who"] and i["source"] and i["as_of"] and i["where"] for i in issues)
    assert report["counts"] == {s: sum(i["severity"] == s for i in issues) for s in SEVERITIES}
