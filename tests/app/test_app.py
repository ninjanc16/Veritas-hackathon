"""
Smoke tests: the loader returns what the app expects, and the app runs without errors
on the fake data - for the focus river AND for a transfer river.
"""
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from app.contract import LATEST_COLUMNS, METRICS_KEYS, OUTLOOK_COLUMNS, PRED_COLUMNS, load

APP_FILE = Path(__file__).resolve().parents[2] / "app" / "streamlit_app.py"


def test_loader_returns_expected_columns_and_keys():
    pred, outlook, latest, metrics, source, problems = load()
    assert list(pred.columns[: len(PRED_COLUMNS)]) == [c for c, _ in PRED_COLUMNS]
    assert list(outlook.columns[: len(OUTLOOK_COLUMNS)]) == [c for c, _ in OUTLOOK_COLUMNS]
    assert list(latest.columns[: len(LATEST_COLUMNS)]) == [c for c, _ in LATEST_COLUMNS]
    assert all(k in metrics for k in METRICS_KEYS)


def _run_app():
    at = AppTest.from_file(str(APP_FILE), default_timeout=60)
    at.run()
    return at


def test_app_shows_the_right_banner_for_its_data():
    at = _run_app()
    assert not at.exception
    _, _, _, metrics, source, problems = load()
    if source == "demo":
        assert any("DEMO DATA" in e.value for e in at.error)          # red banner
    elif not metrics["is_final"]:
        assert any("Provisional results" in w.value for w in at.warning)   # yellow banner
    else:
        assert not at.error and not at.warning                          # final data: no banner


def test_app_runs_for_every_river():
    at = _run_app()
    # The river picker holds the plain river names (the "(transfer test)" label is display-only).
    for river in ["Rio Grande", "Colorado", "Mississippi", "Missouri", "Ohio"]:
        at.sidebar.selectbox[0].set_value(river).run()
        assert not at.exception, f"app crashed on river {river}"


def test_replay_buttons_work():
    at = _run_app()
    at.button[2].click().run()                            # "Next week"
    assert not at.exception


def test_data_checks_are_green_on_demo_data():
    at = _run_app()
    assert any("App counts match metrics.json" in s.value for s in at.sidebar.success)


def _run_with_link(**params):
    """Open the app as if someone clicked a link with these web-address parameters."""
    at = AppTest.from_file(str(APP_FILE), default_timeout=60)
    for key, value in params.items():
        at.query_params[key] = value
    at.run()
    return at


def test_link_opens_the_right_river_county_and_tab():
    _, _, latest, _, *_ = load()
    ohio = latest[latest["river"] == "Ohio"].iloc[1]
    at = _run_with_link(river="Ohio", fips=ohio["fips"], view="Replay")
    assert not at.exception
    assert at.sidebar.selectbox[0].value == "Ohio"
    assert at.sidebar.selectbox[1].value == ohio["fips"]
    assert at.session_state["view"] == "Replay"


def test_bad_link_values_are_ignored():
    at = _run_with_link(river="Nope", fips="00000", view="zzz")
    assert not at.exception
    assert at.sidebar.selectbox[0].value == "Rio Grande"


def test_changing_river_picks_a_valid_county():
    _, _, latest, _, *_ = load()
    ohio = latest[latest["river"] == "Ohio"].iloc[0]
    at = _run_with_link(river="Ohio", fips=ohio["fips"])
    at.sidebar.selectbox[0].set_value("Colorado").run()
    assert not at.exception
    colorado = set(latest[latest["river"] == "Colorado"]["fips"])
    assert at.sidebar.selectbox[1].value in colorado


# --- the "Canal action" tab ----------------------------------------------------------------
def _all_text(at):
    """Every piece of text the app drew (markdown, captions, info boxes), as one string."""
    return " ".join(e.value for group in (at.markdown, at.caption, at.info) for e in group)


def test_canal_tab_opens_for_a_valley_county():
    """Hidalgo is one of the three Valley counties, so the district table shows."""
    _, _, latest, *_ = load()
    if "48215" not in set(latest["fips"]):
        return                                           # demo data has no real counties
    at = _run_with_link(fips="48215", view="Canal action")
    assert not at.exception
    text = _all_text(at)
    assert "Which irrigation districts matter most" in text
    assert "CCID#2 (San Benito)" in " ".join(str(d.value.to_string()) for d in at.dataframe)
    assert "Estimate from published figures" in text
    assert "Read this first" in text


def test_canal_tab_works_without_and_with_the_new_columns(monkeypatch):
    """Other counties show the 'no district table' note; the tab never crashes either way."""
    import app.contract as contract
    # With the pivot columns (the fake files have them).
    monkeypatch.setattr(contract, "load", lambda: (*contract.load_demo(), "demo", []))
    st.cache_data.clear()                # the app caches the loaded files; start fresh
    at = _run_with_link(view="Canal action")
    assert not at.exception
    text = _all_text(at)
    assert "No public district table for this county" in text
    assert "score from the forest that also sees reservoir storage" in text   # new column was used
    # Without them: strip the optional columns and keys.
    def stripped():
        pred, outlook, latest, metrics = contract.load_demo()
        latest = latest.drop(columns=[c for c, _ in contract.OPTIONAL_LATEST_COLUMNS])
        outlook = outlook.drop(columns=["p_season_res"])
        metrics = {k: v for k, v in metrics.items() if k not in contract.OPTIONAL_METRICS_KEYS}
        return pred, outlook, latest, metrics, "demo", []
    monkeypatch.setattr(contract, "load", stripped)
    st.cache_data.clear()
    at = _run_with_link(view="Canal action")
    assert not at.exception
    text = _all_text(at)
    assert "reservoir version is not available yet" in text
    assert "not available yet" in text
    st.cache_data.clear()                # don't leave the fake data cached for other tests


def test_how_good_tab_shows_trigger_losses_and_reservoirs(monkeypatch):
    """The fake files carry the new blocks, so the three new sections fill in; without them they say so."""
    import app.contract as contract
    monkeypatch.setattr(contract, "load", lambda: (*contract.load_demo(), "demo", []))
    st.cache_data.clear()
    at = _run_with_link(view="How good is it")
    assert not at.exception
    headers = [h.value for h in at.header]
    for h in ("Does the forecast work as a pre-season trigger?", "Measured drought losses", "Reservoirs"):
        assert h in headers
    assert any("did about as well as the simple" in str(e.value) for e in at.markdown)

    def stripped():
        pred, outlook, latest, metrics = contract.load_demo()
        metrics = {k: v for k, v in metrics.items() if k not in contract.OPTIONAL_METRICS_KEYS}
        return pred, outlook, latest, metrics, "demo", []
    monkeypatch.setattr(contract, "load", stripped)
    st.cache_data.clear()
    at = _run_with_link(view="How good is it")
    assert not at.exception
    assert sum(1 for e in at.markdown if e.value == "Not available yet.") == 3
    st.cache_data.clear()


def test_canal_map_shows_for_a_valley_county_and_a_county_without_canals():
    from app.mapdata import CANALS_FILE
    _, _, latest, metrics, *_ = load()
    if "canal_priority" not in metrics or not CANALS_FILE.exists():
        return
    at = _run_with_link(fips="48215", view="Canal action")
    assert not at.exception
    assert "Where leaks are likely" in _all_text(at)
    assert not any("Canal map: not available yet" in str(e.value) for e in at.markdown)
    # Every Rio Grande county opens without a crash, with or without canal lines.
    for fips in latest[latest["river"] == "Rio Grande"]["fips"]:
        at = _run_with_link(fips=fips, view="Canal action")
        assert not at.exception, fips


def test_canal_map_says_not_available_without_the_pipeline_keys(monkeypatch):
    import app.contract as contract
    monkeypatch.setattr(contract, "load", lambda: (*contract.load_demo(), "demo", []))
    st.cache_data.clear()
    at = _run_with_link(view="Canal action")
    assert not at.exception
    assert any("Canal map: not available yet" in str(e.value) for e in at.markdown)
    st.cache_data.clear()
