"""Lab manager dashboards. Almost everything is derived from audit_log plus the current form/field rows."""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from app.api.serialize import load_value
from app.api.workflow import workload
from app.auth import ROLE_MANAGER, require_roles
from app.db import get_session
from app.fields import FIELD_NAMES
from app.models import AuditLog, Field, Form
from app.workflow import APPROVED, NEEDS_FIX, PENDING_APPROVAL, RETURNED

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"], dependencies=[Depends(require_roles(ROLE_MANAGER))])

BACKLOG_ORDER = ["processing", NEEDS_FIX, PENDING_APPROVAL, RETURNED, APPROVED, "failed"]
STAGES = ["processing", NEEDS_FIX, PENDING_APPROVAL, RETURNED]  # time spent before approval
UNKNOWN_SENDER = "לא ידוע"


def _since(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=days)


def _status_changes(s: Session, form_ids: Optional[List[int]] = None) -> Dict[int, List[AuditLog]]:
    q = select(AuditLog).where(AuditLog.entity == "form", AuditLog.action == "status_change")
    if form_ids is not None:
        if not form_ids:
            return {}
        q = q.where(AuditLog.entity_id.in_(form_ids))
    out: Dict[int, List[AuditLog]] = defaultdict(list)
    for row in s.exec(q.order_by(AuditLog.at, AuditLog.id)).all():
        out[row.entity_id].append(row)
    return out


def _to_state(row: AuditLog) -> Optional[str]:
    return (load_value(row.after) or {}).get("workflow")


@router.get("/backlog")
def backlog(s: Session = Depends(get_session)):
    counts = {k: 0 for k in BACKLOG_ORDER}
    for status, wf in s.exec(select(Form.status, Form.workflow)).all():
        if status in ("pending", "processing"):
            counts["processing"] += 1
        elif status == "failed":
            counts["failed"] += 1
        elif wf in counts:
            counts[wf] += 1
    return {"states": [{"state": k, "count": counts[k]} for k in BACKLOG_ORDER]}


@router.get("/accuracy")
def accuracy(days: int = Query(14, ge=1, le=365), s: Session = Depends(get_session)):
    """Share of fields in approved forms that nobody had to correct, overall and by approval day."""
    changes = _status_changes(s)
    approved_on: Dict[int, datetime] = {}
    for form_id, rows in changes.items():
        for row in rows:
            if _to_state(row) == APPROVED:
                approved_on[form_id] = row.at
    approved_ids = [f for f in s.exec(select(Form.id).where(Form.workflow == APPROVED)).all()]
    per_day: Dict[str, List[int]] = defaultdict(lambda: [0, 0])  # day -> [untouched, total]
    total = untouched = 0
    since = _since(days)
    if approved_ids:
        for form_id, corrected in s.exec(
                select(Field.form_id, Field.manually_corrected).where(Field.form_id.in_(approved_ids))).all():
            total += 1
            untouched += 0 if corrected else 1
            at = approved_on.get(form_id)
            if at is not None and at >= since:
                cell = per_day[at.date().isoformat()]
                cell[0] += 0 if corrected else 1
                cell[1] += 1
    return {
        "accuracy": round(100 * untouched / total, 1) if total else None,
        "fields": total,
        "approved_forms": len(approved_ids),
        "by_day": [{"day": d, "accuracy": round(100 * u / t, 1), "fields": t}
                   for d, (u, t) in sorted(per_day.items())],
    }


@router.get("/problem-fields")
def problem_fields(days: int = Query(30, ge=1, le=365), s: Session = Depends(get_session)):
    """Manual corrections per field, and per field × sender for the heatmap."""
    rows = s.exec(select(AuditLog).where(AuditLog.action == "field_corrected", AuditLog.at >= _since(days))).all()
    form_ids = list({r.form_id for r in rows if r.form_id is not None})
    sender_of: Dict[int, str] = {}
    if form_ids:
        for fld in s.exec(select(Field).where(Field.form_id.in_(form_ids), Field.name == "sender")).all():
            sender_of[fld.form_id] = load_value(fld.value) or UNKNOWN_SENDER
    totals = {n: 0 for n in FIELD_NAMES}
    cells: Dict[str, Dict[str, int]] = {n: defaultdict(int) for n in FIELD_NAMES}
    for r in rows:
        name = (load_value(r.before) or {}).get("name")
        if name not in totals:
            continue
        totals[name] += 1
        cells[name][sender_of.get(r.form_id, UNKNOWN_SENDER)] += 1
    senders = sorted({sd for c in cells.values() for sd in c}, key=lambda sd: (sd == UNKNOWN_SENDER, sd))
    return {
        "fields": [{"field": n, "corrections": totals[n]} for n in sorted(FIELD_NAMES, key=lambda n: -totals[n])],
        "senders": senders,
        "cells": {n: dict(cells[n]) for n in FIELD_NAMES},
    }


def _stage_hours(form: Form, rows: List[AuditLog]) -> Dict[str, float]:
    """Hours the form spent in each state until it was approved."""
    spent = {k: 0.0 for k in STAGES}
    # forms from before the workflow existed have no "pipeline finished" row: start in the state they left first
    first_before = (load_value(rows[0].before) or {}).get("workflow") if rows else None
    state, entered = first_before or "processing", form.created_at
    for row in rows:
        if entered is not None and state in spent:
            spent[state] += max((row.at - entered).total_seconds(), 0) / 3600
        state, entered = _to_state(row), row.at
        if state == APPROVED:
            break
    return spent


@router.get("/time-to-approval")
def time_to_approval(days: int = Query(14, ge=1, le=365), s: Session = Depends(get_session)):
    forms = {f.id: f for f in s.exec(select(Form).where(Form.workflow == APPROVED)).all()}
    changes = _status_changes(s, list(forms))
    since = _since(days)
    totals: List[float] = []
    stage_sum = {k: 0.0 for k in STAGES}
    per_day: Dict[str, Dict[str, Any]] = {}
    for form_id, form in forms.items():
        rows = changes.get(form_id, [])
        approved_at = next((r.at for r in rows if _to_state(r) == APPROVED), None)
        if approved_at is None or form.created_at is None:
            continue
        spent = _stage_hours(form, rows)
        totals.append(sum(spent.values()))
        for k in STAGES:
            stage_sum[k] += spent[k]
        if approved_at >= since:
            day = per_day.setdefault(approved_at.date().isoformat(), {"forms": 0, **{k: 0.0 for k in STAGES}})
            day["forms"] += 1
            for k in STAGES:
                day[k] += spent[k]
    n = len(totals)
    return {
        "avg_hours": round(sum(totals) / n, 2) if n else None,
        "forms": n,
        "stages": [{"stage": k, "avg_hours": round(stage_sum[k] / n, 2) if n else 0} for k in STAGES],
        "by_day": [
            {"day": d, "forms": v["forms"], **{k: round(v[k] / v["forms"], 2) for k in STAGES}}
            for d, v in sorted(per_day.items())
        ],
    }


@router.get("/workload")
def workload_route(s: Session = Depends(get_session)):
    return workload(s)
