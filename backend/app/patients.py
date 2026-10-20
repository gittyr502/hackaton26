"""Patient file: forms filed under a patient by ID number.

A form is linked automatically only when its ID is valid (check digit) and was read with confidence;
anything weaker is only a suggestion for a person to confirm. A person's decision (manual / rejected) is final.
"""
import json
import re
from typing import Any, Optional

from sqlmodel import Session, select

from app.fields import LEVEL_OK
from app.models import Field, Form
from validators.israeli_id import is_valid_id

LINK_AUTO, LINK_SUGGESTED, LINK_MANUAL, LINK_REJECTED = "auto", "suggested", "manual", "rejected"
FINAL_LINKS = (LINK_MANUAL, LINK_REJECTED)
FILED = (LINK_AUTO, LINK_MANUAL)  # links that put a form in the patient file


def patient_key(value: Any) -> Optional[str]:
    """The 9-digit form of an ID (leading zeros restored), or None when it is not an ID at all."""
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if not digits or len(digits) > 9:
        return None
    return digits.zfill(9)


def _id_of(s: Session, form: Form):
    """(raw ID, read with confidence?) of a commitment (its id_number field) or another document (doc_meta)."""
    if form.doc_type == "commitment":
        fld = s.exec(select(Field).where(Field.form_id == form.id, Field.name == "id_number")).first()
        if fld is None or fld.value is None:
            return None, False
        return json.loads(fld.value), fld.level == LEVEL_OK
    meta = json.loads(form.doc_meta) if form.doc_meta else {}
    return meta.get("id_number"), bool(meta.get("id_confident"))


def link_patient(s: Session, form: Form) -> None:
    """(Re)compute the form's patient link from what was read. The caller commits."""
    if form.id is None or form.patient_link in FINAL_LINKS:
        return
    raw, confident = _id_of(s, form)
    pid = patient_key(raw)
    if pid is None:
        form.patient_id, form.patient_link = None, None
    else:
        form.patient_id = pid
        form.patient_link = LINK_AUTO if confident and is_valid_id(pid) else LINK_SUGGESTED
    s.add(form)


def backfill(s: Session) -> None:
    """Forms read before the patient file existed."""
    forms = s.exec(select(Form).where(Form.status == "done", Form.patient_link == None,  # noqa: E711
                                      Form.parent_form_id == None)).all()  # noqa: E711
    for form in forms:
        link_patient(s, form)
    s.commit()
