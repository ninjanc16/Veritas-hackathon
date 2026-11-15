"""Lets the tests do `from app.contract import ...` by putting the repo root on the import path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
