import pytest

from validators.israeli_id import is_valid_id


@pytest.mark.parametrize("value", ["000000018", "123456782", "039337423", "000000026",
                                   "18", "39337423", "11223344"])  # without leading zeros
def test_valid_ids(value):
    assert is_valid_id(value)


@pytest.mark.parametrize("value", ["123456789", "000000019", "12345678", "1234567890", "12345678a", ""])
def test_invalid_ids(value):
    assert not is_valid_id(value)
