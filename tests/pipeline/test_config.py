"""Checks that config.py still holds the choices fixed in ARCHITECTURE_PIPELINE.md.

If someone changes a fixed number by accident, these tests fail and say which one.
"""
from farmdrought import config as c


def test_fixed_choices_match_the_architecture_doc():
    # Rivers: one focus river, five in total
    assert c.FOCUS_RIVER == "Rio Grande"
    assert sorted(c.RIVERS) == ["Colorado", "Mississippi", "Missouri", "Ohio", "Rio Grande"]
    # Targets
    assert (c.D2_CLASS, c.ALERT_WEEKS, c.SEASON_WEEKS, c.SEASON_RUN, c.YEAR_WEEKS) == (3, 4, 26, 8, 52)
    # Geography and scoring
    assert (c.BUFFER_KM, c.NEIGHBOR_KM, c.MISS_COST) == (50, 150, 3)
    # Time splits
    assert c.TRAIN == (2000, 2014) and c.VAL == (2015, 2018)
    assert c.TEST_START == 2019 and c.OUTLOOK_TEST == (2008, 2025)


def test_season_threshold_is_the_break_even_point():
    # A miss costs MISS_COST false alarms, so warning pays off above 1 / (1 + MISS_COST)
    assert c.SEASON_THRESHOLD == 1 / (1 + c.MISS_COST)


def test_splits_do_not_overlap():
    # Train must end before validation starts, and validation before test
    assert c.TRAIN[1] < c.VAL[0] and c.VAL[1] < c.TEST_START


def test_gauge_ids_look_like_usgs_ids():
    assert len(c.GAUGES) == 4
    for gauge_id in c.GAUGES.values():
        assert gauge_id.startswith("USGS-") and len(gauge_id) == len("USGS-08330000")


def test_paths_stay_inside_pipeline_owned_folders():
    # Every path this track writes to must be under data/ or reports/ (never app/)
    for path in (c.PREDICTIONS, c.OUTLOOK, c.LATEST, c.METRICS, c.RAW, c.INTERIM):
        top_folder = path.relative_to(c.ROOT).parts[0]
        assert top_folder in ("data", "reports")


def test_raw_data_files_were_downloaded():
    for path in (c.USDM_JSON, c.RIVERS_GEOJSON, c.COUNTIES_GEOJSON, c.ONI_TXT):
        assert path.exists(), f"missing input file: {path}"
