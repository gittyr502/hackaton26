"""The audit trail: one AuditLog row per workflow transition or field mutation.

record() only adds the row to the caller's session, so it commits (or rolls back) together with the change.
"""
import json
from typing import Any, Optional

from sqlmodel import Session

from app.models import AuditLog, User


def _dump(v: Any) -> Optional[str]:
    return None if v is None else json.dumps(v, ensure_ascii=False)


def record(
    s: Session,
    user: Optional[User],
    action: str,
    entity: str,
    entity_id: int,
    form_id: Optional[int] = None,
    before: Any = None,
    after: Any = None,
    comment: Optional[str] = None,
) -> AuditLog:
    row = AuditLog(
        user_id=user.id if user else None, action=action, entity=entity, entity_id=entity_id,
        form_id=form_id if form_id is not None else (entity_id if entity == "form" else None),
        before=_dump(before), after=_dump(after), comment=comment,
    )
    s.add(row)
    return row
