import asyncio
import re
import shutil
from typing import List, Set

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlmodel import Session, select

from app.api.serialize import batch_detail
from app.auth import (ROLE_INTAKE, ROLE_MANAGER, check_batch_owner, check_batch_view, get_current_user,
                      require_roles)
from app.config import get_settings
from app.db import get_session
from app.logging_utils import get_logger, log_event
from app.models import AuditLog, Batch, ExportRecord, ExportSetting, Field, Form, SourceFile, User
from pipeline import control
from pipeline.runner import process_batch

router = APIRouter(prefix="/api/batches", tags=["batches"])
log = get_logger("api")

ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".heic", ".heif", ".tif", ".tiff"}
_tasks: Set[asyncio.Task] = set()  # keep references so background tasks are not GC'd


def start_background(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _safe_name(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1]
    return re.sub(r"[^\w.\-א-ת]", "_", name)[:120] or "file"


def _get_batch(s: Session, batch_id: int) -> Batch:
    batch = s.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(404, "batch not found")
    return batch


@router.post("")
async def create_batch(files: List[UploadFile] = File(...), s: Session = Depends(get_session),
                       user: User = Depends(require_roles(ROLE_INTAKE, ROLE_MANAGER))):
    if not files:
        raise HTTPException(400, "no files")
    for f in files:
        ext = "." + (f.filename or "").rsplit(".", 1)[-1].lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(400, f"unsupported file type: {f.filename}")

    batch = Batch(uploaded_by=user.id)
    s.add(batch)
    s.commit()
    s.refresh(batch)
    upload_dir = get_settings().batches_dir / str(batch.id) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(files):
        dest = upload_dir / f"{i + 1}_{_safe_name(f.filename or 'file')}"
        with open(dest, "wb") as out:
            shutil.copyfileobj(f.file, out)
        s.add(SourceFile(batch_id=batch.id, filename=f.filename or dest.name, path=str(dest),
                         content=dest.read_bytes()))
    s.commit()
    log_event(log, "batch_created", batch_id=batch.id, files=len(files))
    start_background(process_batch(batch.id))
    return batch_detail(s, batch)


@router.get("")
def list_batches(s: Session = Depends(get_session), user: User = Depends(get_current_user)):
    query = select(Batch).order_by(Batch.id.desc())
    if user.role == ROLE_INTAKE:
        mine = select(Form.batch_id).where(Form.assigned_to == user.id)
        query = query.where((Batch.uploaded_by == user.id) | Batch.id.in_(mine))
    batches = s.exec(query).all()
    out = []
    for b in batches:
        n_files = len(s.exec(select(SourceFile.id).where(SourceFile.batch_id == b.id)).all())
        n_forms = len(s.exec(select(Form.id).where(Form.batch_id == b.id)).all())
        out.append({"id": b.id, "created_at": b.created_at.isoformat(), "status": b.status,
                    "files": n_files, "forms": n_forms})
    return out


@router.get("/{batch_id}")
def get_batch(batch_id: int, s: Session = Depends(get_session), user: User = Depends(get_current_user)):
    batch = _get_batch(s, batch_id)
    check_batch_view(s, user, batch)
    return batch_detail(s, batch)


def _running_batch(s: Session, batch_id: int, user: User) -> Batch:
    batch = _get_batch(s, batch_id)
    check_batch_owner(user, batch)
    if batch.status != "processing":
        raise HTTPException(409, "batch is not processing")
    return batch


@router.post("/{batch_id}/pause")
async def pause_batch(batch_id: int, s: Session = Depends(get_session),
                       user: User = Depends(get_current_user)):
    _running_batch(s, batch_id, user)
    control.pause(batch_id)
    log_event(log, "batch_paused", batch_id=batch_id)
    return {"ok": True, "paused": True}


@router.post("/{batch_id}/resume")
async def resume_batch(batch_id: int, s: Session = Depends(get_session),
                       user: User = Depends(get_current_user)):
    _running_batch(s, batch_id, user)
    control.resume(batch_id)
    log_event(log, "batch_resumed", batch_id=batch_id)
    return {"ok": True, "paused": False}


@router.post("/{batch_id}/cancel")
async def cancel_batch(batch_id: int, s: Session = Depends(get_session),
                       user: User = Depends(get_current_user)):
    _running_batch(s, batch_id, user)
    control.cancel(batch_id)
    log_event(log, "batch_cancelled", batch_id=batch_id)
    return {"ok": True}


@router.delete("/{batch_id}")
def delete_batch(batch_id: int, s: Session = Depends(get_session), user: User = Depends(get_current_user)):
    batch = _get_batch(s, batch_id)
    check_batch_owner(user, batch)
    if batch.status == "processing":
        raise HTTPException(409, "batch is still processing")
    form_ids = [f.id for f in s.exec(select(Form).where(Form.batch_id == batch_id)).all()]
    if form_ids:
        for fld in s.exec(select(Field).where(Field.form_id.in_(form_ids))).all():
            s.delete(fld)
        for row in s.exec(select(AuditLog).where(AuditLog.form_id.in_(form_ids))).all():
            s.delete(row)
    for model in (Form, SourceFile, ExportRecord):
        for row in s.exec(select(model).where(model.batch_id == batch_id)).all():
            s.delete(row)
    setting = s.get(ExportSetting, batch_id)
    if setting is not None:
        s.delete(setting)
    s.delete(batch)
    s.commit()
    shutil.rmtree(get_settings().batches_dir / str(batch_id), ignore_errors=True)
    log_event(log, "batch_deleted", batch_id=batch_id)
    return {"ok": True}
