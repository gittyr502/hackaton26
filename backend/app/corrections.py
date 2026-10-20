"""Keeping the Correction rows in step with what reviewers do to fields (see pipeline.learning)."""
import json
from typing import Any, Dict

from sqlmodel import Session, select

from app.models import Correction, Field, User
from pipeline.normalizers import values_equal


def _dump(v: Any):
    return None if v is None else json.dumps(v, ensure_ascii=False)


def _load(v):
    return None if v is None else json.loads(v)


def record(s: Session, user: User, fld: Field, before: Dict[str, Any]) -> None:
    """Call after a manual edit of fld, with `before` = its value/level just before the edit.

    The first edit remembers what the pipeline showed; later edits only change the answer.
    Editing back to what the pipeline showed means there was no mistake, so nothing is kept.
    """
    existing = s.exec(select(Correction).where(Correction.field_id == fld.id)).first()
    model_value = _load(existing.model_value) if existing else before["value"]
    model_level = existing.model_level if existing else before["level"]
    new_value = _load(fld.value)
    if values_equal(model_value, new_value):
        if existing:
            s.delete(existing)
        return
    row = existing or Correction(
        form_id=fld.form_id, field_id=fld.id, field_name=fld.name, model_value=_dump(model_value),
        raw_value=fld.raw_value, model_level=model_level, model_confidence=fld.confidence,
        handwritten=any(r.get("code") == "handwritten" for r in json.loads(fld.reasons or "[]")),
    )
    row.corrected_value = _dump(new_value)
    row.user_id = user.id
    s.add(row)


def discard(s: Session, fld: Field) -> None:
    """The edit was undone (reset to the model's reading): it is no longer a correction."""
    for row in s.exec(select(Correction).where(Correction.field_id == fld.id)).all():
        s.delete(row)


def detach_form(s: Session, form_id: int) -> None:
    """The form is read again and its Field rows replaced: keep the lessons, drop the dangling link."""
    for row in s.exec(select(Correction).where(Correction.form_id == form_id)).all():
        row.field_id = None
        s.add(row)
