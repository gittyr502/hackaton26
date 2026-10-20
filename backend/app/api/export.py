"""Export screen: summary + live preview, per-batch export options (kept in the DB) and the file download."""
import hashlib
from typing import Any, Dict, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.serialize import batch_detail, confidence_rows, export_rows, export_stats
from app.auth import (ROLE_APPROVER, ROLE_INTAKE, ROLE_MANAGER, check_batch_view, has_role, require_roles)
from app.config import get_settings
from app.db import get_session
from app.fields import FIELD_NAMES
from app.logging_utils import get_logger, log_event
from app.models import Batch, ExportRecord, ExportSetting, Form, User
from app.workflow import APPROVED
from export.excel import csv_bytes, encrypt_xlsx, json_bytes, workbook_bytes

router = APIRouter(prefix="/api/batches", tags=["export"])
# manager: everything; approver: any batch; intake clerk: her own batches, once something in them is approved
exporter = require_roles(ROLE_MANAGER, ROLE_APPROVER, ROLE_INTAKE)
log = get_logger("export")

FORMATS: Dict[str, Tuple[str, str]] = {
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "xlsx"),
    "csv": ("text/csv; charset=utf-8", "csv"),
    "json": ("application/json", "json"),
}
PREVIEW_LIMIT = 500


class ExportOptions(BaseModel):
    format: str = "xlsx"
    include_details: bool = True
    include_source_links: bool = True
    password_protect: bool = False


class ExportRequest(BaseModel):
    """Options for one download. Fields left out fall back to the saved ones; the password is never saved."""
    format: Optional[str] = None
    include_details: Optional[bool] = None
    include_source_links: Optional[bool] = None
    password: Optional[str] = None
    link_base: Optional[str] = None  # origin the source-image links should point to


def _batch(s: Session, batch_id: int, user: User) -> Batch:
    batch = s.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(404, "batch not found")
    if not has_role(user, ROLE_MANAGER, ROLE_APPROVER):
        check_batch_view(s, user, batch)
        if s.exec(select(Form.id).where(Form.batch_id == batch_id, Form.workflow == APPROVED)).first() is None:
            raise HTTPException(403, "nothing in this batch is approved yet")
    return batch


def scan_number(batch: Batch) -> str:
    return f"MED-{batch.created_at.year}-{batch.id:04d}"


def _options(s: Session, batch_id: int) -> ExportOptions:
    row = s.get(ExportSetting, batch_id)
    return ExportOptions(**row.model_dump(exclude={"batch_id"})) if row else ExportOptions()


def _check_format(fmt: str) -> None:
    if fmt not in FORMATS:
        raise HTTPException(400, f"unsupported format: {fmt}")


def build_file(s: Session, batch: Batch, opts: ExportOptions, link_base: str = "",
               password: Optional[str] = None) -> Dict[str, Any]:
    """Build the export from DB rows. Returns bytes plus the facts the screen shows about the file."""
    cfg = get_settings().export
    rows = export_rows(s, batch.id)
    if opts.format == "xlsx" and opts.include_source_links:
        for r in rows:
            r["_image_url"] = f"{link_base.rstrip('/')}/api/forms/{r['_form_id']}/image"
    sheets = 1
    if opts.format == "xlsx":
        details = confidence_rows(s, batch.id) if opts.include_details else None
        sheets += 1 if details is not None else 0
        data = workbook_bytes(rows, cfg, details, opts.include_source_links)
        if password:
            data = encrypt_xlsx(data, password)
    elif opts.format == "csv":
        data = csv_bytes(rows, cfg)
    else:
        data = json_bytes(rows, cfg)
    return {
        "data": data,
        "media_type": FORMATS[opts.format][0],
        "filename": f"MedScan_Export_{batch.id:04d}.{FORMATS[opts.format][1]}",
        "sheets": sheets,
        "rows": len(rows),
        "fields": len(rows) * len(FIELD_NAMES),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _file_info(f: Dict[str, Any], opts: ExportOptions) -> Dict[str, Any]:
    return {
        "filename": f["filename"], "size_bytes": f["size_bytes"], "sheets": f["sheets"],
        "rows": f["rows"], "fields": f["fields"],
        # an encrypted file differs on every save, so its checksum is only known at download time
        "sha256": None if (opts.password_protect and opts.format == "xlsx") else f["sha256"],
    }


@router.get("/{batch_id}/export/summary")
def export_summary(batch_id: int, request: Request, s: Session = Depends(get_session),
                   user: User = Depends(exporter)):
    batch = _batch(s, batch_id, user)
    detail = batch_detail(s, batch)
    cfg = get_settings().export
    opts = _options(s, batch_id)
    stats = export_stats(s, batch_id)
    rows = export_rows(s, batch_id)
    seconds = None
    if batch.started_at and batch.finished_at:
        seconds = round((batch.finished_at - batch.started_at).total_seconds(), 1)
    last = s.exec(
        select(ExportRecord).where(ExportRecord.batch_id == batch_id).order_by(ExportRecord.id.desc())
    ).first()
    return {
        "review": detail["counts"].get("review", 0),
        "failed_forms": detail["failed_forms"],
        "forms": sum(1 for f in detail["forms"] if f["status"] == "done"),
        "processing": detail["status"] == "processing",
        **stats,
        "readable_pct": round(100 * stats["pages_done"] / stats["pages"]) if stats["pages"] else 0,
        "scan_number": scan_number(batch),
        "processing_seconds": seconds,
        "sheet_name": cfg.get("sheet_name", "Sheet1"),
        "columns": [{"field": c["field"], "header": c["header"]} for c in cfg["columns"]],
        "preview": rows[:PREVIEW_LIMIT],
        "confidence_preview": confidence_rows(s, batch_id)[:PREVIEW_LIMIT],
        "options": opts.model_dump(),
        "file": _file_info(build_file(s, batch, opts, str(request.base_url)), opts),
        "last_export": last.model_dump(mode="json") if last else None,
    }


@router.put("/{batch_id}/export/options")
def save_options(batch_id: int, body: ExportOptions, request: Request, s: Session = Depends(get_session),
                 user: User = Depends(exporter)):
    batch = _batch(s, batch_id, user)
    _check_format(body.format)
    row = s.get(ExportSetting, batch_id) or ExportSetting(batch_id=batch_id)
    for k, v in body.model_dump().items():
        setattr(row, k, v)
    s.add(row)
    s.commit()
    return {"options": body.model_dump(),
            "file": _file_info(build_file(s, batch, body, str(request.base_url)), body)}


def _download(s: Session, batch_id: int, body: ExportRequest, request: Request, user: User) -> Response:
    batch = _batch(s, batch_id, user)
    saved = _options(s, batch_id)
    opts = ExportOptions(
        format=body.format or saved.format,
        include_details=saved.include_details if body.include_details is None else body.include_details,
        include_source_links=(saved.include_source_links if body.include_source_links is None
                              else body.include_source_links),
        password_protect=saved.password_protect,
    )
    _check_format(opts.format)
    password = body.password if opts.format == "xlsx" else None
    if opts.password_protect and opts.format == "xlsx" and not password:
        raise HTTPException(400, "password required")
    f = build_file(s, batch, opts, body.link_base or str(request.base_url), password or None)
    s.add(ExportRecord(batch_id=batch_id, format=opts.format, filename=f["filename"],
                       size_bytes=f["size_bytes"], sha256=f["sha256"], rows=f["rows"],
                       protected=bool(password)))
    s.commit()
    log_event(log, "batch_exported", batch_id=batch_id, format=opts.format, protected=bool(password), user_id=user.id)
    return Response(
        content=f["data"], media_type=f["media_type"],
        headers={"Content-Disposition": f'attachment; filename="{f["filename"]}"'},
    )


@router.post("/{batch_id}/export")
def export_post(batch_id: int, body: ExportRequest, request: Request, s: Session = Depends(get_session),
                user: User = Depends(exporter)):
    return _download(s, batch_id, body, request, user)


@router.get("/{batch_id}/export")
def export_get(
    batch_id: int,
    request: Request,
    format: Optional[str] = Query(None),
    details: Optional[bool] = Query(None, description="xlsx only: add a sheet with per-field confidence"),
    s: Session = Depends(get_session),
    user: User = Depends(exporter),
):
    return _download(s, batch_id, ExportRequest(format=format, include_details=details), request, user)
