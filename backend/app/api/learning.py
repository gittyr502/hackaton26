"""What the system has learned from human corrections, for the lab manager to see."""
from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy import case
from sqlmodel import Session, func, select

from app.auth import ROLE_MANAGER, require_roles
from app.config import get_settings
from app.db import get_session
from app.models import Correction, Form
from app.workflow import APPROVED
from pipeline.learning import load_lessons

router = APIRouter(prefix="/api", tags=["learning"], dependencies=[Depends(require_roles(ROLE_MANAGER))])


@router.get("/learning")
def learning(s: Session = Depends(get_session)) -> Dict[str, Any]:
    settings = get_settings()
    lessons = load_lessons(s, settings.pipeline.get("learning"), settings.senders)
    per_field = {
        name: {"corrections": n, "confident_errors": confident}
        for name, n, confident in s.exec(
            select(Correction.field_name, func.count(Correction.id),
                   func.sum(case((Correction.model_level == "ok", 1), else_=0)))
            .join(Form, Form.id == Correction.form_id).where(Form.workflow == APPROVED)
            .group_by(Correction.field_name)
        ).all()
    }
    pending = s.exec(select(func.count(Correction.id)).join(Form, Form.id == Correction.form_id)
                     .where(Form.workflow != APPROVED)).one()
    return {"per_field": per_field, "awaiting_approval": pending, **lessons.summary()}
