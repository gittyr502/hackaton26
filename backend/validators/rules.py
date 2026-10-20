"""Validation rules written by the lab manager, in their structured (machine) form.

A rule is plain data, evaluated deterministically: no model is involved when it runs.

    {"combine": "all" | "any",
     "when": [{"field": "sender", "op": "eq", "value": "מכבי"}, ...],     # empty = always
     "then": {"field": "referral_number", "check": "required", "arg": null}}

A form *violates* the rule when the conditions hold and the check fails. The Hebrew explanation shown to
the manager is generated from the same spec (describe_he), so what she approves is exactly what runs.
"""
import re
from datetime import date
from typing import Any, Dict, List

from app.fields import FIELD_NAMES
from pipeline.normalizers import normalize_date, values_equal
from validators.senders import match_sender

OPS = ("eq", "neq", "in", "contains", "empty", "not_empty")
CHECKS = ("required", "forbidden", "regex", "in_list", "date_not_before")
NO_VALUE_OPS = ("empty", "not_empty")

FIELD_LABELS_HE = {
    "full_name": "שם מלא",
    "id_number": "ת.ז.",
    "central_numbers": "מספרים מרכזיים",
    "receipt_date": "תאריך קבלה",
    "sender": "גורם שולח",
    "commitment_numbers": "מספרי התחייבות",
    "test_type": "סוג בדיקה",
    "referral_number": "מספר הפניה",
}


def validate_spec(spec: Any) -> List[str]:
    """Error codes; [] means the rule can run."""
    if not isinstance(spec, dict):
        return ["spec_not_object"]
    errors = []
    if spec.get("combine", "all") not in ("all", "any"):
        errors.append("bad_combine")
    when = spec.get("when") or []
    if not isinstance(when, list):
        return errors + ["when_not_list"]
    for cond in when:
        if not isinstance(cond, dict) or cond.get("field") not in FIELD_NAMES:
            errors.append("unknown_field")
        elif cond.get("op") not in OPS:
            errors.append("unknown_op")
        elif cond["op"] not in NO_VALUE_OPS and cond.get("value") in (None, "", []):
            errors.append("missing_value")
    then = spec.get("then")
    if not isinstance(then, dict) or then.get("field") not in FIELD_NAMES:
        errors.append("unknown_then_field")
    elif then.get("check") not in CHECKS:
        errors.append("unknown_check")
    elif then["check"] in ("regex", "in_list", "date_not_before") and then.get("arg") in (None, "", []):
        errors.append("missing_arg")
    elif then["check"] == "regex":
        try:
            re.compile(str(then["arg"]))
        except re.error:
            errors.append("bad_regex")
    return sorted(set(errors))


def referenced_fields(spec: Dict[str, Any]) -> List[str]:
    names = [c.get("field") for c in spec.get("when") or []] + [(spec.get("then") or {}).get("field")]
    return [n for n in dict.fromkeys(names) if n in FIELD_NAMES]


def _items(value: Any) -> List[Any]:
    if value is None:
        return []
    return [v for v in value if v not in (None, "")] if isinstance(value, list) else [value]


def _same(field: str, a: Any, b: Any, senders_cfg: Dict[str, Any]) -> bool:
    """Equal the way a person means it: senders by canonical name (aliases count), text without case."""
    if field == "sender":
        ca = match_sender(str(a), senders_cfg)[0] or str(a)
        cb = match_sender(str(b), senders_cfg)[0] or str(b)
        return values_equal(ca, cb)
    return values_equal(str(a).strip(), str(b).strip())


def _cond_holds(cond: Dict[str, Any], values: Dict[str, Any], senders_cfg: Dict[str, Any]) -> bool:
    field, op, want = cond["field"], cond["op"], cond.get("value")
    have = _items(values.get(field))
    if op == "empty":
        return not have
    if op == "not_empty":
        return bool(have)
    wanted = _items(want) if isinstance(want, list) else [want]
    if op == "eq":
        return any(_same(field, h, w, senders_cfg) for h in have for w in wanted)
    if op == "neq":
        return bool(have) and not any(_same(field, h, w, senders_cfg) for h in have for w in wanted)
    if op == "in":
        return any(_same(field, h, w, senders_cfg) for h in have for w in wanted)
    if op == "contains":
        return any(str(w).strip() and str(w).strip().casefold() in str(h).casefold() for h in have for w in wanted)
    return False


def _check_fails(then: Dict[str, Any], values: Dict[str, Any], senders_cfg: Dict[str, Any]) -> bool:
    field, check, arg = then["field"], then["check"], then.get("arg")
    have = _items(values.get(field))
    if check == "required":
        return not have
    if check == "forbidden":
        return bool(have)
    if not have:  # format checks apply to values that exist; "required" is a separate rule
        return False
    if check == "regex":
        return any(re.fullmatch(str(arg), str(h)) is None for h in have)
    if check == "in_list":
        allowed = _items(arg) if isinstance(arg, list) else [arg]
        return any(not any(_same(field, h, a, senders_cfg) for a in allowed) for h in have)
    if check == "date_not_before":
        limit = normalize_date(str(arg))
        try:
            return any(date.fromisoformat(str(h)) < date.fromisoformat(limit) for h in have)
        except ValueError:
            return False
    return False


def evaluate(spec: Dict[str, Any], values: Dict[str, Any], senders_cfg: Dict[str, Any]) -> bool:
    """True when the form (field name -> current value) violates the rule."""
    conds = spec.get("when") or []
    held = [_cond_holds(c, values, senders_cfg) for c in conds]
    applies = (any(held) if spec.get("combine") == "any" else all(held)) if conds else True
    return applies and _check_fails(spec["then"], values, senders_cfg)


# ---------- Hebrew explanation (from the spec itself) ----------

_OP_HE = {"eq": "=", "neq": "≠", "in": "אחד מ:", "contains": "מכיל", "empty": "ריק", "not_empty": "לא ריק"}
_CHECK_HE = {"required": "חובה", "forbidden": "חייב להיות ריק", "regex": "חייב להתאים לתבנית",
             "in_list": "חייב להיות אחד מ:", "date_not_before": "לא לפני"}


def _fmt(v: Any) -> str:
    return ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)


def describe_parts(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Chips for the UI: conditions and the action, each as short Hebrew text."""
    conds = []
    for c in spec.get("when") or []:
        label = FIELD_LABELS_HE.get(c["field"], c["field"])
        if c["op"] in NO_VALUE_OPS:
            conds.append(f"{label} {_OP_HE[c['op']]}")
        else:
            conds.append(f"{label} {_OP_HE[c['op']]} {_fmt(c.get('value'))}")
    then = spec["then"]
    action = f"{FIELD_LABELS_HE.get(then['field'], then['field'])}: {_CHECK_HE[then['check']]}"
    if then.get("arg") not in (None, "", []):
        action += f" {_fmt(then['arg'])}"
    return {"conditions": conds, "joiner": "או" if spec.get("combine") == "any" else "וגם", "action": action}


def describe_he(spec: Dict[str, Any]) -> str:
    parts = describe_parts(spec)
    if not parts["conditions"]:
        return f"תמיד ← {parts['action']}"
    joiner = f" {parts['joiner']} "
    return f"כאשר {joiner.join(parts['conditions'])} ← {parts['action']}"
