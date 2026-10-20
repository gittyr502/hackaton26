"""Possible duplicates: a commitment number already seen on another form. Only a warning, never a deletion."""
import json
from typing import Any, Iterable

from sqlmodel import Session, select

from app.models import Field, Form
from pipeline.normalizers import values_equal


def _as_list(v: Any) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def has_duplicate_commitment(s: Session, form_id: int, numbers: Iterable[Any]) -> bool:
    wanted = [n for n in _as_list(list(numbers)) if n]
    if not wanted:
        return False
    rows = s.exec(
        select(Field.value).join(Form, Form.id == Field.form_id).where(
            Field.name == "commitment_numbers", Field.form_id != form_id, Field.value != None,  # noqa: E711
            Form.parent_form_id == None, Form.doc_type == "commitment",  # noqa: E711
        )
    ).all()
    for raw in rows:
        try:
            theirs = _as_list(json.loads(raw))
        except ValueError:
            continue
        if any(values_equal(a, b) for a in wanted for b in theirs):
            return True
    return False
