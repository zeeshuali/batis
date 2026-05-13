from unittest.mock import patch

import pytest
from sqlalchemy import text

from app.services.census_tracts_loader import load_bay_area_tracts


_FAKE_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"GEOID": "06001400100", "COUNTY": "001"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[-122.27, 37.81], [-122.27, 37.82],
                     [-122.26, 37.82], [-122.26, 37.81],
                     [-122.27, 37.81]]
                ]
            }
        },
        {
            "type": "Feature",
            "properties": {"GEOID": "06001400200", "COUNTY": "001"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[-122.28, 37.80], [-122.28, 37.81],
                     [-122.27, 37.81], [-122.27, 37.80],
                     [-122.28, 37.80]]
                ]
            }
        }
    ]
}


@pytest.fixture
def cleanup_tracts(db_conn):
    try:
        yield
    finally:
        db_conn.execute(text(
            "DELETE FROM census_tracts WHERE tract_geoid LIKE '060014001%' "
            "OR tract_geoid LIKE '060014002%'"
        ))
        db_conn.commit()


def test_load_bay_area_tracts_upserts(db_conn, cleanup_tracts):
    with patch("app.services.census_tracts_loader.requests.get") as mock_get:
        def fake_get(url, **kwargs):
            where = kwargs.get("params", {}).get("where", "")
            class R:
                status_code = 200
                def raise_for_status(self): pass
                def json(self_):
                    if "COUNTY='001'" in where:
                        return _FAKE_GEOJSON
                    return {"type": "FeatureCollection", "features": []}
            return R()
        mock_get.side_effect = fake_get

        n = load_bay_area_tracts(db_conn)
        db_conn.commit()

    assert n >= 2

    rows = db_conn.execute(text(
        "SELECT tract_geoid, county_fips, ST_GeometryType(geom) "
        "FROM census_tracts "
        "WHERE tract_geoid IN ('06001400100','06001400200') "
        "ORDER BY tract_geoid"
    )).all()
    assert len(rows) == 2
    assert rows[0][0] == "06001400100"
    assert rows[0][1] == "001"
    assert rows[0][2] == "ST_MultiPolygon"


def test_load_bay_area_tracts_idempotent(db_conn, cleanup_tracts):
    with patch("app.services.census_tracts_loader.requests.get") as mock_get:
        def fake_get(url, **kwargs):
            where = kwargs.get("params", {}).get("where", "")
            class R:
                status_code = 200
                def raise_for_status(self): pass
                def json(self_):
                    if "COUNTY='001'" in where:
                        return _FAKE_GEOJSON
                    return {"type": "FeatureCollection", "features": []}
            return R()
        mock_get.side_effect = fake_get

        n1 = load_bay_area_tracts(db_conn); db_conn.commit()
        n2 = load_bay_area_tracts(db_conn); db_conn.commit()

    cnt = db_conn.execute(text(
        "SELECT COUNT(*) FROM census_tracts "
        "WHERE tract_geoid IN ('06001400100','06001400200')"
    )).scalar()
    assert cnt == 2
