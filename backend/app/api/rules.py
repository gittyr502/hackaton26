"""Validation rules in plain Hebrew: convert, try on existing forms, save, activate, disable."""
import json
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app import audit, events
from app.auth import ROLE_ADMIN, ROLE_MANAGER, require_roles
from app.config import get_settings
from app.db import get_session
from app.fields import LEVEL_REVIEW
from app.logging_utils import get_logger, log_event
from app.models import Field, Form, User, ValidationRule
from app.rules_nl import dry_run, explain, parse_rule, violating_forms
from app.workflow import NEEDS_FIX, PENDING_APPROVAL, RETURNED
from validators.rules import validate_spec

router = APIRouter(prefix="/api/rules", tags=["rules"],
                   dependencies=[Depends(require_roles(ROLE_MANAGER, ROLE_ADMIN))])
log = get_logger("api")

OPEN_WORKFLOWS = [NEEDS_FIX, PENDING_APPROVAL, RETURNED]  # approved forms are never touched


def get_rules_client() -> Any:
    """The Claude client used to translate rules (overridden in tests)."""
    from pipeline.runner import build_context

    return build_context(get_settings()).client


class ParseBody(BaseModel):
    text: str


class SpecBody(BaseModel):
    spec: Dict[str, Any]


class RuleBody(BaseModel):
    name: str
    source_text: str = ""
    spec: Dict[str, Any]


class RuleUpdate(BaseModel):
    name: Optional[str] = None
    source_text: Optional[str] = None
    spec: Optional[Dict[str, Any]] = None


class ActivateBody(BaseModel):
    apply_open: bool = True


def _checked_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    errors = validate_spec(spec)
    if errors:
        raise HTTPException(422, {"code": "invalid_rule", "detail": errors})
    return spec


def _rule_dict(r: ValidationRule) -> Dict[str, Any]:
    spec = json.loads(r.spec or "{}")
    return {"id": r.id, "name": r.name, "source_text": r.source_text, "spec": spec, "status": r.status,
            "version": r.version, "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            "last_dry_run": json.loads(r.last_dry_run) if r.last_dry_run else None,
            **(explain(spec) if not validate_spec(spec) else {"description": None, "parts": None})}


def _get(s: Session, rule_id: int) -> ValidationRule:
    r = s.get(ValidationRule, rule_id)
    if r is None:
        raise HTTPException(404, "rule not found")
    return r


def _snapshot(r: ValidationRule) -> Dict[str, Any]:
    return {"name": r.name, "status": r.status, "version": r.version, "spec": json.loads(r.spec or "{}")}


@router.get("")
def list_rules(s: Session = Depends(get_session)):
    return [_rule_dict(r) for r in s.exec(select(ValidationRule).order_by(ValidationRule.id.desc())).all()]


@router.post("/parse")
async def parse(body: ParseBody, client: Any = Depends(get_rules_client)):
    if not body.text.strip():
        raise HTTPException(422, {"code": "empty_rule", "detail": "empty rule"})
    settings = get_settings()
    model = (settings.pipeline.get("models") or {}).get("rules")
    return await parse_rule(body.text, client, settings.senders, model=model)


@router.post("/dry-run")
def try_rule(body: SpecBody, s: Session = Depends(get_session)):
    spec = _checked_spec(body.spec)
    return {**dry_run(s, spec, get_settings().senders), **explain(spec)}


@router.post("", status_code=201)
def create_rule(body: RuleBody, s: Session = Depends(get_session),
                user: User = Depends(require_roles(ROLE_MANAGER, ROLE_ADMIN))):
    spec = _checked_spec(body.spec)
    result = dry_run(s, spec, get_settings().senders, limit=0)
    r = ValidationRule(name=body.name.strip()[:80] or "כלל", source_text=body.source_text,
                       spec=json.dumps(spec, ensure_ascii=False), created_by=user.id,
                       last_dry_run=json.dumps({"checked": result["checked"], "flagged": result["flagged"],
                                                "at": datetime.utcnow().isoformat()}))
    s.add(r)
    s.flush()
    audit.record(s, user, "rule_created", "rule", r.id, after=_snapshot(r))
    s.commit()
    s.refresh(r)
    log_event(log, "rule_created", rule_id=r.id, user_id=user.id)
    return _rule_dict(r)


@router.patch("/{rule_id}")
def update_rule(rule_id: int, body: RuleUpdate, s: Session = Depends(get_session),
                user: User = Depends(require_roles(ROLE_MANAGER, ROLE_ADMIN))):
    r = _get(s, rule_id)
    before = _snapshot(r)
    if body.name is not None:
        r.name = body.name.strip()[:80] or r.name
    if body.source_text is not None:
        r.source_text = body.source_text
    if body.spec is not None:
        r.spec = json.dumps(_checked_spec(body.spec), ensure_ascii=False)
        r.version += 1
        if r.status == "active":  # an edited rule is tried and approved again before it runs
            r.status = "draft"
    r.updated_at = datetime.utcnow()
    s.add(r)
    audit.record(s, user, "rule_updated", "rule", r.id, before=before, after=_snapshot(r))
    s.commit()
    s.refresh(r)
    return _rule_dict(r)


def _flag_open_forms(s: Session, r: ValidationRule, user: User) -> int:
    """Add the rule's reason to open forms that break it; a form waiting for approval goes back to the clerk."""
    spec = json.loads(r.spec)
    target, code = spec["then"]["field"], f"rule:{r.id}"
    flagged = 0
    for form_id in violating_forms(s, spec, get_settings().senders, OPEN_WORKFLOWS):
        form = s.get(Form, form_id)
        fld = s.exec(select(Field).where(Field.form_id == form_id, Field.name == target)).first()
        if fld is None:  # read before this field existed
            fld = Field(form_id=form_id, name=target, level=LEVEL_REVIEW, reasons="[]")
        reasons = json.loads(fld.reasons or "[]")
        if any(x.get("code") == code for x in reasons):
            continue
        before = {"name": target, "level": fld.level}
        fld.reasons = json.dumps(reasons + [{"kind": "validation", "code": code}], ensure_ascii=False)
        fld.level = LEVEL_REVIEW
        fld.version = (fld.version or 0) + 1
        s.add(fld)
        s.flush()
        audit.record(s, user, "rule_flagged", "field", fld.id, form_id=form_id, before=before,
                     after={"name": target, "level": LEVEL_REVIEW, "rule": r.id})
        if form.workflow == PENDING_APPROVAL:
            form.workflow = NEEDS_FIX
            s.add(form)
            audit.record(s, user, "status_change", "form", form_id, before={"workflow": PENDING_APPROVAL},
                         after={"workflow": NEEDS_FIX}, comment=f"rule:{r.id}")
        flagged += 1
        events.bump(form.batch_id)
    return flagged


@router.post("/{rule_id}/activate")
def activate(rule_id: int, body: ActivateBody, s: Session = Depends(get_session),
             user: User = Depends(require_roles(ROLE_MANAGER, ROLE_ADMIN))):
    r = _get(s, rule_id)
    _checked_spec(json.loads(r.spec or "{}"))
    before = _snapshot(r)
    r.status, r.activated_by, r.updated_at = "active", user.id, datetime.utcnow()
    s.add(r)
    audit.record(s, user, "rule_activated", "rule", r.id, before=before, after=_snapshot(r))
    flagged = _flag_open_forms(s, r, user) if body.apply_open else 0
    s.commit()
    s.refresh(r)
    log_event(log, "rule_activated", rule_id=r.id, user_id=user.id, flagged_open=flagged)
    return {**_rule_dict(r), "flagged_open": flagged}


@router.post("/{rule_id}/disable")
def disable(rule_id: int, s: Session = Depends(get_session),
            user: User = Depends(require_roles(ROLE_MANAGER, ROLE_ADMIN))):
    r = _get(s, rule_id)
    before = _snapshot(r)
    r.status, r.updated_at = "disabled", datetime.utcnow()
    s.add(r)
    audit.record(s, user, "rule_disabled", "rule", r.id, before=before, after=_snapshot(r))
    s.commit()
    s.refresh(r)
    return _rule_dict(r)
