"""Shared test setup: build the real county-week panel once and reuse it in every test."""
import pytest

from farmdrought.drought import build_panel


@pytest.fixture(scope="session")
def panel():
    return build_panel()
