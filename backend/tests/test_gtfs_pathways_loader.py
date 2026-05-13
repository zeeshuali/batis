import io
import zipfile

import pytest
from sqlalchemy import text

from app.services.gtfs_pathways_loader import load_pathways_from_zip_bytes


_PATHWAYS_CSV = (
    "pathway_id,from_stop_id,to_stop_id,pathway_mode,"
    "is_bidirectional,length,traversal_time,stair_count,max_slope\n"
    "p1,A,B,1,1,42.0,30,0,0\n"
    "p2,B,C,2,0,12.0,15,18,0\n"
    "p3,B,D,5,1,8.0,20,0,0\n"
)
_LEVELS_CSV = (
    "level_id,level_index,level_name\n"
    "L0,0,Concourse\n"
    "L1,1,Platform\n"
)


def _make_zip(include_pathways: bool, include_levels: bool) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("stops.txt", "stop_id\nA\nB\nC\nD\n")
        if include_pathways:
            zf.writestr("pathways.txt", _PATHWAYS_CSV)
        if include_levels:
            zf.writestr("levels.txt", _LEVELS_CSV)
    return buf.getvalue()


@pytest.fixture
def cleanup_pathways(db_conn):
    try:
        yield
    finally:
        db_conn.execute(text("DELETE FROM gtfs_pathways WHERE agency_id = 'TESTPW'"))
        db_conn.execute(text("DELETE FROM gtfs_levels   WHERE agency_id = 'TESTPW'"))
        db_conn.commit()


def test_load_pathways_writes_pathways_and_levels(db_conn, cleanup_pathways):
    n = load_pathways_from_zip_bytes(db_conn, "TESTPW", _make_zip(True, True))
    db_conn.commit()
    assert n == 5  # 3 pathways + 2 levels

    pw_rows = db_conn.execute(text(
        "SELECT pathway_id, from_stop_id, to_stop_id, pathway_mode "
        "FROM gtfs_pathways WHERE agency_id = 'TESTPW' "
        "ORDER BY pathway_id"
    )).all()
    assert pw_rows == [
        ("p1", "A", "B", 1),
        ("p2", "B", "C", 2),
        ("p3", "B", "D", 5),
    ]
    lvl_rows = db_conn.execute(text(
        "SELECT level_id, level_index, level_name "
        "FROM gtfs_levels WHERE agency_id = 'TESTPW' ORDER BY level_id"
    )).all()
    assert len(lvl_rows) == 2


def test_load_pathways_skips_when_no_pathways_txt(db_conn, cleanup_pathways):
    n = load_pathways_from_zip_bytes(db_conn, "TESTPW", _make_zip(False, False))
    db_conn.commit()
    assert n == 0


def test_load_pathways_is_idempotent(db_conn, cleanup_pathways):
    load_pathways_from_zip_bytes(db_conn, "TESTPW", _make_zip(True, True))
    load_pathways_from_zip_bytes(db_conn, "TESTPW", _make_zip(True, True))
    db_conn.commit()
    cnt = db_conn.execute(text(
        "SELECT COUNT(*) FROM gtfs_pathways WHERE agency_id = 'TESTPW'"
    )).scalar()
    assert cnt == 3  # not 6
