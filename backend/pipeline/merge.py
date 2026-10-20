"""One commitment over several pages: continuation pages are merged into the form they continue.

Every page is still read on its own (so nothing on page 2 is missed); afterwards the values of a
continuation page are folded into its parent form:
- a field empty on the parent is taken from the continuation page;
- list fields (central / commitment numbers) are unioned;
- two different readings of a single value keep the parent's, and go to review (pages_disagree).

The child form stays (with its own image and fields) but is hidden behind its parent; the parent's
fields before the merge are kept so a human can split the pages apart again.
"""
import json
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from app import audit
from app.fields import LEVEL_REVIEW, MULTI_FIELDS
from app.logging_utils import get_logger, log_event
from app.models import Field, Form, User
from app.workflow import APPROVED, initial_workflow
from pipeline.base import SKIPPED_TYPES
from pipeline.normalizers import values_equal

log = get_logger("merge")

MERGE_REASONS = ("merged_pages", "pages_disagree")


def _load(v: Optional[str]) -> Any:
    return None if v is None else json.loads(v)


def _dump(v: Any) -> Optional[str]:
    return None if v is None else json.dumps(v, ensure_ascii=False)


def _reasons(form: Form) -> List[str]:
    try:
        out = json.loads(form.reasons or "[]")
    except ValueError:
        return []
    return out if isinstance(out, list) else []


def _set_reasons(form: Form, codes: List[str]) -> None:
    form.reasons = json.dumps(list(dict.fromkeys(codes)), ensure_ascii=False)


def _fields(s: Session, form_id: int) -> Dict[str, Field]:
    return {f.name: f for f in s.exec(select(Field).where(Field.form_id == form_id)).all()}


def _snapshot(fields: Dict[str, Field]) -> str:
    return json.dumps({n: {
        "value": f.value, "raw_value": f.raw_value, "confidence": f.confidence, "level": f.level,
        "reasons": f.reasons, "box": f.box, "box_verified": f.box_verified,
        "manually_corrected": f.manually_corrected,
    } for n, f in fields.items()}, ensure_ascii=False)


def _add_field_reason(fld: Field, code: str) -> None:
    reasons = json.loads(fld.reasons or "[]")
    if not any(r.get("code") == code for r in reasons):
        reasons.append({"kind": "soft", "code": code})
    fld.reasons = json.dumps(reasons, ensure_ascii=False)


def _merge_field(name: str, into: Field, other: Field) -> None:
    a, b = _load(into.value), _load(other.value)
    if b is None or b == []:
        return
    if a is None or a == []:
        into.value, into.raw_value = other.value, other.raw_value
        into.confidence, into.level, into.reasons = other.confidence, other.level, other.reasons
        into.box, into.box_verified = None, False  # the frame belongs to the other page's image
        return
    if name in MULTI_FIELDS:
        merged = list(a) + [x for x in b if not any(values_equal(x, y) for y in a)]
        if len(merged) != len(a):
            into.value = _dump(merged)
            if other.level == LEVEL_REVIEW:
                into.level = LEVEL_REVIEW
        return
    if not values_equal(a, b):
        into.level = LEVEL_REVIEW
        _add_field_reason(into, "pages_disagree")


def _workflow_of(s: Session, form: Form) -> str:
    return initial_workflow((f.level for f in _fields(s, form.id).values()), _reasons(form))


def merge_into(s: Session, parent: Form, child: Form, user: Optional[User] = None) -> None:
    """Fold child's fields into parent and hide child behind it. The caller commits."""
    if parent.workflow == APPROVED or child.workflow == APPROVED:
        raise HTTPException(409, "approved forms cannot be merged")
    pf = _fields(s, parent.id)
    if parent.premerge_fields is None:
        parent.premerge_fields = _snapshot(pf)
    for name, other in _fields(s, child.id).items():
        if name in pf:
            _merge_field(name, pf[name], other)
            s.add(pf[name])
    # pages already behind the child follow it
    for grand in s.exec(select(Form).where(Form.parent_form_id == child.id)).all():
        grand.parent_form_id = parent.id
        s.add(grand)
    before = {"workflow": child.workflow, "parent_form_id": child.parent_form_id}
    child.parent_form_id, child.workflow, child.doc_type = parent.id, None, "continuation"
    _set_reasons(parent, _reasons(parent) + ["merged_pages"]
                 + (["pages_disagree"] if any("pages_disagree" in (f.reasons or "") for f in pf.values()) else []))
    parent_before = parent.workflow
    parent.workflow = _workflow_of(s, parent)
    s.add(child)
    s.add(parent)
    audit.record(s, user, "pages_merged", "form", child.id, before=before,
                 after={"workflow": None, "parent_form_id": parent.id})
    if parent_before != parent.workflow:
        audit.record(s, user, "status_change", "form", parent.id, before={"workflow": parent_before},
                     after={"workflow": parent.workflow})


def _top_level_before(s: Session, form: Form) -> Optional[Form]:
    """The form this page would continue: the nearest earlier page of the same file that is a commitment."""
    earlier = s.exec(select(Form).where(Form.source_file_id == form.source_file_id, Form.id != form.id)
                     .order_by(Form.page_index, Form.region_index)).all()
    key = (form.page_index, form.region_index or 0)
    candidates = [f for f in earlier if (f.page_index, f.region_index or 0) < key and f.status == "done"
                  and (f.doc_type or "commitment") not in SKIPPED_TYPES]
    if not candidates:
        return None
    prev = candidates[-1]
    return s.get(Form, prev.parent_form_id) if prev.parent_form_id is not None else prev


def auto_merge_file(s: Session, source_file_id: int) -> int:
    """Merge every continuation page of a file into the form before it. Returns how many were merged."""
    merged = 0
    forms = s.exec(select(Form).where(Form.source_file_id == source_file_id)
                   .order_by(Form.page_index, Form.region_index)).all()
    for form in forms:
        if form.doc_type != "continuation" or form.parent_form_id is not None or form.status != "done":
            continue
        parent = _top_level_before(s, form)
        if parent is None or parent.workflow == APPROVED:
            form.doc_type = "commitment"  # nothing to continue: it is read as a form of its own
            s.add(form)
            continue
        merge_into(s, parent, form)
        merged += 1
    s.commit()
    if merged:
        log_event(log, "pages_merged", source_file_id=source_file_id, merged=merged)
    return merged


def merge_previous(s: Session, form: Form, user: User) -> Form:
    """Manual: this page continues the one before it."""
    if form.parent_form_id is not None:
        raise HTTPException(409, "form is already merged")
    parent = _top_level_before(s, form)
    if parent is None:
        raise HTTPException(409, "no earlier page to merge with")
    merge_into(s, parent, form, user)
    s.commit()
    return parent


def split(s: Session, parent: Form, user: User) -> List[int]:
    """Manual: undo the merge. The parent gets back its own reading; every page is a form again."""
    if parent.workflow == APPROVED:
        raise HTTPException(409, "approved forms cannot be split")
    children = s.exec(select(Form).where(Form.parent_form_id == parent.id)).all()
    if not children:
        raise HTTPException(409, "form has no merged pages")
    if parent.premerge_fields:
        snap = json.loads(parent.premerge_fields)
        for name, fld in _fields(s, parent.id).items():
            old = snap.get(name)
            if old is None:
                continue
            for k, v in old.items():
                setattr(fld, k, v)
            fld.version = (fld.version or 0) + 1
            s.add(fld)
    parent.premerge_fields = None
    _set_reasons(parent, [r for r in _reasons(parent) if r not in MERGE_REASONS])
    before = parent.workflow
    parent.workflow = _workflow_of(s, parent)
    s.add(parent)
    audit.record(s, user, "status_change", "form", parent.id, before={"workflow": before},
                 after={"workflow": parent.workflow})
    ids = []
    for child in children:
        child.parent_form_id, child.doc_type = None, "commitment"
        child.workflow = _workflow_of(s, child)
        if child.assigned_to is None:
            child.assigned_to = parent.assigned_to
        s.add(child)
        audit.record(s, user, "pages_split", "form", child.id, before={"parent_form_id": parent.id},
                     after={"workflow": child.workflow, "parent_form_id": None})
        ids.append(child.id)
    s.commit()
    return ids


def remerge_children(s: Session, parent_id: int) -> None:
    """After the parent was read again: fold its pages in again on top of the fresh reading."""
    parent = s.get(Form, parent_id)
    if parent is None:
        return
    children = s.exec(select(Form).where(Form.parent_form_id == parent_id).order_by(Form.page_index)).all()
    if not children:
        return
    parent.premerge_fields = None
    for child in children:
        child.parent_form_id = None
        merge_into(s, parent, child)
    s.commit()
