"""Streamlit hosting reads app/requirements.txt, so it must be an exact copy of requirements-app.txt."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_requirements_files_are_identical():
    assert (ROOT / "requirements-app.txt").read_text() == (ROOT / "app" / "requirements.txt").read_text()
