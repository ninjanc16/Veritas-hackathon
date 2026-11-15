"""Tests for the live-data refresh: the file conversions must be exact."""
from farmdrought.refresh import oni_table, week_of

NOAA_SAMPLE = """ SEAS  YR   TOTAL   ANOM
  NDJ 1997  28.90   2.40
  DJF 1998  28.60   2.22
  JFM 1998  28.50   1.91
  NDJ 1998  25.10  -1.47
  DJF 1999  25.00  -1.51
"""


def test_el_nino_file_is_turned_into_one_line_per_year():
    # 1997 is before our first year, so it is dropped. The sample's out-of-order line is left out here.
    lines = oni_table("\n".join(NOAA_SAMPLE.splitlines()[:4] + NOAA_SAMPLE.splitlines()[5:]))
    assert lines == ["1998 2.22 1.91", "1999 -1.51"]


def test_el_nino_seasons_out_of_order_are_refused():
    import pytest
    with pytest.raises(AssertionError):
        oni_table(NOAA_SAMPLE)   # 1998 jumps from JFM to NDJ: a gap, so the file is refused


def test_newest_week_is_week0_plus_the_number_of_weeks():
    assert week_of({"week0": "2000-01-04", "weeks": 1}) == "2000-01-04"
    assert week_of({"week0": "2000-01-04", "weeks": 3}) == "2000-01-18"
