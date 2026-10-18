import json
from pathlib import Path
from typing import Any, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlmodel import Session

from app import audit
from app.api.batches import start_background
from app.api.serialize import field_dict, load_value
from app.auth import check_batch_view, check_form_editor, get_current_user
from app.config import get_settings
from app.db import get_session
from app.fields import LEVEL_EMPTY, LEVEL_OK
from app.logging_utils import get_logger, log_event
from app.models import Batch, Field, Form, User
from app.workflow import APPROVED
from pipeline.normalizers import normalize_field
from pipeline.runner import retry_form
from validators.senders import canonical_names

router = APIRouter(prefix="/api", tags=["forms"], dependencies=[Depends(get_current_user)])
log = get_logger("api")


class FieldUpdate(BaseModel):
    value: Optional[Union[str, List[str]]] = None


@router.get("/forms/{form_id}/image")
def form_image(form_id: int, s: Session = Depends(get_session), user: User = Depends(get_current_user)):
    form = s.get(Form, form_id)
    if form is not None:
        check_batch_view(s, user, s.get(Batch, form.batch_id))
    if form is not None and form.image_data:
        return Response(form.image_data, media_type="image/png")
    if form is None or not form.image_path or not Path(form.image_path).exists():
        raise HTTPException(404, "image not found")
    return FileResponse(form.image_path, media_type="image/png")


@router.post("/forms/{form_id}/retry")
async def retry(form_id: int, s: Session = Depends(get_session), user: User = Depends(get_current_user)):
    form = s.get(Form, form_id)
    if form is None:
        raise HTTPException(404, "form not found")
    check_form_editor(s, user, form)
    if form.status == "processing":
        raise HTTPException(409, "form is already processing")
    form.status, form.error = "processing", None
    s.add(form)
    s.commit()
    start_background(retry_form(form_id))
    return {"ok": True}


def _get_field(s: Session, field_id: int, user: User) -> Field:
    """The field, if this user may edit its form. Approved forms are frozen."""
    fld = s.get(Field, field_id)
    if fld is None:
        raise HTTPException(404, "field not found")
    form = s.get(Form, fld.form_id)
    check_form_editor(s, user, form)
    if form.workflow == APPROVED:
        raise HTTPException(409, "form is already approved")
    return fld


def _snapshot(fld: Field) -> dict:
    return {"value": load_value(fld.value), "level": fld.level}


def _audit(s: Session, user: User, action: str, fld: Field, before: dict) -> None:
    audit.record(s, user, action, "field", fld.id, form_id=fld.form_id, before={"name": fld.name, **before},
                 after={"name": fld.name, **_snapshot(fld)})


@router.patch("/fields/{field_id}")
def update_field(field_id: int, body: FieldUpdate, s: Session = Depends(get_session),
                 user: User = Depends(get_current_user)):
    """A manual correction is the truth: normalize its format and mark it ok (or empty)."""
    fld = _get_field(s, field_id, user)
    before = _snapshot(fld)
    value: Any = body.value
    if isinstance(value, str) and not value.strip():
        value = None
    value, _ = normalize_field(fld.name, value, get_settings().senders)
    fld.value = None if value is None else json.dumps(value, ensure_ascii=False)
    fld.level = LEVEL_EMPTY if value is None else LEVEL_OK
    fld.manually_corrected = True
    s.add(fld)
    _audit(s, user, "field_corrected", fld, before)
    s.commit()
    s.refresh(fld)
    log_event(log, "field_corrected", field_id=field_id, form_id=fld.form_id)
    return field_dict(fld)


@router.post("/fields/{field_id}/approve")
def approve_field(field_id: int, s: Session = Depends(get_session), user: User = Depends(get_current_user)):
    fld = _get_field(s, field_id, user)
    before = _snapshot(fld)
    fld.level = LEVEL_EMPTY if fld.value is None else LEVEL_OK
    s.add(fld)
    _audit(s, user, "field_approved", fld, before)
    s.commit()
    s.refresh(fld)
    log_event(log, "field_approved", field_id=field_id, form_id=fld.form_id)
    return field_dict(fld)


@router.post("/fields/{field_id}/reset")
def reset_field(field_id: int, s: Session = Depends(get_session), user: User = Depends(get_current_user)):
    """Undo manual edits: put back what the model originally read (normalized again)."""
    fld = _get_field(s, field_id, user)
    before = _snapshot(fld)
    raw = load_value(fld.raw_value)
    value, _ = normalize_field(fld.name, raw, get_settings().senders)
    fld.value = None if value is None else json.dumps(value, ensure_ascii=False)
    fld.manually_corrected = False
    if value is None:
        fld.level = LEVEL_EMPTY
    elif fld.level == LEVEL_EMPTY or fld.reasons in (None, "", "[]"):
        fld.level = LEVEL_OK
    s.add(fld)
    _audit(s, user, "field_reset", fld, before)
    s.commit()
    s.refresh(fld)
    log_event(log, "field_reset", field_id=field_id, form_id=fld.form_id)
    return field_dict(fld)


@router.get("/senders")
def senders():
    return canonical_names(get_settings().senders)
