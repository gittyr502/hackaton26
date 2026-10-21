"""Identity cross-check of a read commitment against the patients already in the system.

An ID number can only belong to one person, so once it is read with confidence it says who the form is about:
- the name is unsure / empty / garbled: it is taken to be the name already filed under that ID;
- the name is read clearly but is another name than the one filed: one of them is wrong, so both fields are flagged.
Names are compared only within the same script (Hebrew / Latin / Arabic / Cyrillic): "דנה כהן" and "Dana Cohen"
may well be one person, and there is no telling them apart here.
"""
import json
import unicodedata
from collections import Counter
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz
from sqlmodel import Session, select

from app.fields import LEVEL_OK, LEVEL_REVIEW
from app.models import Field, Form
from app.patients import FILED, patient_key
from app.workflow import APPROVED
from pipeline.base import FormDoc
from pipeline.normalizers import normalize_name
from pipeline.stages.confidence import DEFAULT_THRESHOLD
from validators.israeli_id import is_valid_id

DEFAULT_ID_MIN_CONFIDENCE = 0.70  # the ID is trusted to identify the person above this
DEFAULT_NAME_MATCH = 75  # similarity (0-100) from which two names count as the same person
NAME_FROM_PATIENT = "name_from_patient_file"
CONFLICT = "id_name_conflict"


def script_of(name: str) -> Optional[str]:
    """The script most of the letters of a name are written in, or None when it has no letters."""
    counts: Counter = Counter()
    for ch in name:
        if ch.isalpha():
            label = unicodedata.name(ch, "")
            counts[next((s for s in ("HEBREW", "ARABIC", "CYRILLIC", "LATIN") if label.startswith(s)), "OTHER")] += 1
    return counts.most_common(1)[0][0] if counts else None


def same_person(a: str, b: str, min_score: float) -> bool:
    a, b = normalize_name(a).casefold(), normalize_name(b).casefold()
    return a == b or fuzz.token_sort_ratio(a, b) >= min_score


def known_names(s: Session, key: str, exclude_form_id: Optional[int]) -> List[str]:
    """Names filed under this ID by other commitments, most common first.

    Approved forms are the trusted ones: when there are any, only their names count.
    """
    forms = s.exec(select(Form).where(
        Form.status == "done", Form.parent_form_id == None,  # noqa: E711
        Form.doc_type == "commitment", Form.patient_id == key, Form.patient_link.in_(list(FILED)),
    )).all()
    forms = [f for f in forms if f.id != exclude_form_id]
    approved = [f for f in forms if f.workflow == APPROVED]
    forms = approved or forms
    if not forms:
        return []
    ids = [f.id for f in forms]
    names = Counter()
    for raw in s.exec(select(Field.value).where(Field.form_id.in_(ids), Field.name == "full_name")).all():
        name = json.loads(raw) if raw else None
        if isinstance(name, str) and name.strip():
            names[name] += 1
    return [n for n, _ in names.most_common()]


def reconcile(s: Session, doc: FormDoc, form_id: Optional[int], pipeline_cfg: Optional[Dict[str, Any]] = None) -> None:
    """Apply the identity rules to the fields of a freshly read form (in place). Idempotent."""
    cfg = (pipeline_cfg or {}).get("identity") or {}
    ident, name = doc.fields.get("id_number"), doc.fields.get("full_name")
    if doc.doc_type != "commitment" or ident is None or name is None or ident.value is None:
        return
    id_min = float(cfg.get("id_min_confidence", DEFAULT_ID_MIN_CONFIDENCE))
    key = patient_key(ident.value)
    id_trusted = (key is not None and is_valid_id(key) and ident.legible and ident.confidence >= id_min
                  and not any(r["kind"] in ("validation", "double_check") for r in ident.reasons))
    if not id_trusted:
        return
    names = known_names(s, key, form_id)
    if not names:
        return

    threshold = float(((pipeline_cfg or {}).get("confidence") or {}).get("threshold", DEFAULT_THRESHOLD))
    name_sure = name.value is not None and name.legible and name.confidence >= threshold
    if not name_sure:
        _take_filed_name(name, names[0])
        return
    min_score = float(cfg.get("name_match", DEFAULT_NAME_MATCH))
    script = script_of(str(name.value))
    comparable = [n for n in names if script_of(n) == script]
    if comparable and not any(same_person(str(name.value), n, min_score) for n in comparable):
        for fr in (name, ident):
            fr.add_reason("validation", CONFLICT)
            fr.level = LEVEL_REVIEW


def _take_filed_name(name, filed: str) -> None:
    """The ID is known, the name read here is not reliable: it is the name filed under that ID."""
    if name.value is not None and name.raw_value is None:
        name.raw_value = name.value
    name.value = filed
    # What made the read unsure no longer matters; a lab rule (validation) still does.
    name.reasons = [r for r in name.reasons if r["kind"] == "validation"]
    name.add_reason("info", NAME_FROM_PATIENT)
    name.level = LEVEL_REVIEW if any(r["kind"] == "validation" for r in name.reasons) else LEVEL_OK
