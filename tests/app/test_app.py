"""
Smoke tests: the loader returns what the app expects, and the app runs without errors
on the fake data - for the focus river AND for a transfer river.
"""
from pathlib import Path

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


def test_app_runs_on_demo_data_and_shows_red_banner():
    at = _run_app()
    assert not at.exception
    assert any("DEMO DATA" in e.value for e in at.error)


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
