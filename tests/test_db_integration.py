import pytest

from zurini.data import db
from zurini.data.dummy import generate_dummy_bars

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


def test_schema_rejects_duplicate_symbol_timestamp():
    db.reset_market_bars()
    bars = generate_dummy_bars(seed=7477)
    db.insert_bars(bars)

    with pytest.raises(Exception):
        db.insert_bars([bars[0]])
