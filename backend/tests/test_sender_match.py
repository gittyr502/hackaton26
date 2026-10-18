from pipeline.normalizers import normalize_field
from validators.senders import is_canonical, match_sender


def test_exact_name(senders_cfg):
    assert match_sender("כללית", senders_cfg) == ("כללית", 100.0, True)


def test_alias(senders_cfg):
    name, _, exact = match_sender("תל השומר", senders_cfg)
    assert (name, exact) == ("שיבא", True)
    assert match_sender("Maccabi", senders_cfg)[0] == "מכבי"


def test_fuzzy_match_flags_soft_reason(senders_cfg):
    value, reasons = normalize_field("sender", "שירותי בריאות כלליתת", senders_cfg)
    assert value == "כללית"
    assert {"kind": "soft", "code": "sender_fuzzy_match"} in reasons


def test_no_match_keeps_raw_value(senders_cfg):
    name, _, _ = match_sender("מרפאת שיניים פרטית", senders_cfg)
    assert name is None
    value, _ = normalize_field("sender", "מרפאת שיניים פרטית", senders_cfg)
    assert value == "מרפאת שיניים פרטית"
    assert not is_canonical(value, senders_cfg)
