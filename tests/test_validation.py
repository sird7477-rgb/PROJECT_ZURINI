from dataclasses import replace
from decimal import Decimal

import pytest

from zurini.data.dummy import generate_dummy_bars
from zurini.data.validation import BarValidationError, validate_bars


def test_validation_rejects_negative_volume_and_value():
    bar = generate_dummy_bars()[0]

    with pytest.raises(BarValidationError, match="volume"):
        validate_bars([replace(bar, volume=-1)])

    with pytest.raises(BarValidationError, match="value"):
        validate_bars([replace(bar, value=Decimal("-1"))])


def test_validation_rejects_invalid_ohlc_relationships():
    bar = generate_dummy_bars()[0]

    with pytest.raises(BarValidationError, match="high"):
        validate_bars([replace(bar, high=bar.low - Decimal("1"))])

    with pytest.raises(BarValidationError, match="open"):
        validate_bars([replace(bar, open=bar.high + Decimal("1"))])

    with pytest.raises(BarValidationError, match="close"):
        validate_bars([replace(bar, close=bar.low - Decimal("1"))])


def test_validation_rejects_duplicate_symbol_timestamp():
    bar = generate_dummy_bars()[0]

    with pytest.raises(BarValidationError, match="duplicate"):
        validate_bars([bar, bar])
