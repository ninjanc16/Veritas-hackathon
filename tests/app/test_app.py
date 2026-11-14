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
