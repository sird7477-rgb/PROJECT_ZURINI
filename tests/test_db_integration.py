import pytest

from zurini.data import db
from zurini.data.dummy import generate_dummy_bars
from zurini.data.large_dummy import (
    generate_symbol_metadata,
    get_large_dummy_profile,
    iter_large_dummy_index_bars,
    iter_large_dummy_market_bars,
)

pytestmark = pytest.mark.integration


def test_schema_loader_and_ordered_date_range_fetch_roundtrip():
    db.reset_market_bars()
    bars = generate_dummy_bars(seed=7477)

    assert db.insert_bars(bars) == len(bars)
    fetched = db.fetch_bars("ZRN001", start=bars[3].timestamp, end=bars[7].timestamp)

    assert len(fetched) == 5
    assert fetched == sorted(fetched, key=lambda bar: (bar.symbol, bar.timestamp))
    assert fetched[0].symbol == bars[3].symbol
    assert fetched[0].timestamp == bars[3].timestamp
    assert fetched[-1].timestamp == bars[7].timestamp


def test_multi_symbol_schema_load_and_fetch_roundtrip():
    db.reset_market_bars()
    bars = generate_dummy_bars(symbol="ZRN001") + generate_dummy_bars(symbol="ZRN002")

    assert db.insert_bars(bars) == len(bars)
    first = db.fetch_bars("ZRN001")
    second = db.fetch_bars("ZRN002")

    assert len(first) == 30
    assert len(second) == 30
    assert {bar.symbol for bar in first + second} == {"ZRN001", "ZRN002"}


def test_schema_rejects_duplicate_symbol_timestamp():
    db.reset_market_bars()
    bars = generate_dummy_bars(seed=7477)
    db.insert_bars(bars)

    with pytest.raises(Exception):
        db.insert_bars([bars[0]])


def test_workflow_lock_releases_after_exception():
    with pytest.raises(RuntimeError, match="sentinel"):
        with db.workflow_lock(timeout_seconds=0):
            raise RuntimeError("sentinel")

    with db.workflow_lock(timeout_seconds=0):
        pass


def test_workflow_lock_times_out_when_already_held():
    with db.workflow_lock(timeout_seconds=0):
        with pytest.raises(RuntimeError, match="already running"):
            with db.workflow_lock(timeout_seconds=0):
                pass


def test_phase_two_staging_tables_exist_for_indices_and_symbol_metadata():
    db.reset_rehearsal_tables()

    with db._connect() as conn:
        index_count = conn.execute("SELECT count(*) FROM index_bars").fetchone()[0]
        metadata_count = conn.execute("SELECT count(*) FROM symbol_metadata").fetchone()[0]

    assert index_count == 0
    assert metadata_count == 0


def test_synthetic_rehearsal_loads_market_index_and_metadata_tables():
    profile = get_large_dummy_profile("smoke")
    market_bars = list(iter_large_dummy_market_bars(profile))
    index_bars = list(iter_large_dummy_index_bars(profile))
    metadata = generate_symbol_metadata(profile)
    db.reset_rehearsal_tables()

    assert db.insert_symbol_metadata(metadata) == profile.symbol_count
    assert db.insert_bars(market_bars) == profile.market_bar_count
    assert db.insert_index_bars(index_bars) == profile.index_bar_count

    with db._connect() as conn:
        market_count = conn.execute("SELECT count(*) FROM market_bars").fetchone()[0]
        index_count = conn.execute("SELECT count(*) FROM index_bars").fetchone()[0]
        metadata_count = conn.execute("SELECT count(*) FROM symbol_metadata").fetchone()[0]
        index_codes = {
            row[0]
            for row in conn.execute("SELECT DISTINCT index_code FROM index_bars ORDER BY index_code").fetchall()
        }

    assert market_count == profile.market_bar_count
    assert index_count == profile.index_bar_count
    assert metadata_count == profile.symbol_count
    assert index_codes == set(profile.index_codes)
