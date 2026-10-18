from datetime import date

from pipeline.normalizers import (
    normalize_date, normalize_field, normalize_id, normalize_multi, to_display_date, values_equal,
)
from validators.dates import check_date


def test_id_digits_without_leading_zeros():
    assert normalize_id("12-345-678 2") == "123456782"
    assert normalize_id("18") == "18"
    assert normalize_id("011223344") == "11223344"
    assert normalize_id("") == ""


def test_dates_day_first_to_iso():
    assert normalize_date("05/03/2026") == "2026-03-05"
    assert normalize_date("5.3.26") == "2026-03-05"
    assert normalize_date("05-03-2026") == "2026-03-05"
    assert normalize_date("2026-03-05") == "2026-03-05"


def test_unparseable_date_is_kept_for_validation():
    assert normalize_date("31/02/2026") == "31/02/2026"
    assert check_date("31/02/2026") == "invalid_date"


def test_future_date_flagged():
    assert check_date("2026-03-05", today=date(2026, 10, 15)) is None
    assert check_date("2027-01-01", today=date(2026, 10, 15)) == "future_date"


def test_multi_value_split_and_dedupe():
    assert normalize_multi("123, 456;789\n123") == ["123", "456", "789"]
    assert normalize_multi(["11 22", "33,", None]) == ["11", "22", "33"]
    assert normalize_multi("") == []


def test_normalize_field_nulls(senders_cfg):
    assert normalize_field("full_name", None, senders_cfg) == (None, [])
    assert normalize_field("central_numbers", " , ", senders_cfg) == (None, [])
    assert normalize_field("full_name", "  דנה   ", senders_cfg)[0] == "דנה"


def test_display_date_and_equality():
    assert to_display_date("2026-03-05") == "05/03/2026"
    assert values_equal(["1", "2"], ["2", "1"])
    assert values_equal(None, None)
    assert not values_equal("a", None)


def test_sniff_tiff(tmp_path):
    from pipeline.stages.ingest import sniff

    for i, head in enumerate((b"II*\x00rest", b"MM\x00*rest")):
        f = tmp_path / f"t{i}.tif"
        f.write_bytes(head + b"\x00" * 16)
        assert sniff(f) == "image/tiff"


def test_full_name_any_script_kept_as_written():
    assert normalize_field("full_name", "  ישראל   ישראלי ", {})[0] == "ישראל ישראלי"
    assert normalize_field("full_name", "محمد خليل", {})[0] == "محمد خليل"
    assert normalize_field("full_name", "Иван Петров.", {})[0] == "Иван Петров"
    assert normalize_field("full_name", "John Smith-Cohen", {})[0] == "John Smith-Cohen"


def test_full_name_keeps_trailing_geresh():
    assert normalize_field("full_name", "ג'ורג'", {})[0] == "ג'ורג'"
    assert normalize_field("full_name", "צ׳רלי -", {})[0] == "צ׳רלי"


def test_values_equal_ignores_case_and_unicode_form():
    assert values_equal("IVAN", "ivan")
    assert values_equal("Иван", "иван")
    assert values_equal("é", "é")  # decomposed vs composed
    assert not values_equal("דנה כהן", "דנה כחן")
