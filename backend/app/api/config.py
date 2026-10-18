"""Mappings (export columns/headers, sender aliases, pipeline) are stored in the DB and editable here."""
import json
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.auth import ROLE_MANAGER, get_current_user, require_roles
from app.db import get_session
from app.models import ConfigEntry

router = APIRouter(prefix="/api/config", tags=["config"], dependencies=[Depends(get_current_user)])
NAMES = ("export", "senders", "pipeline")


@router.get("/{name}")
def get_config(name: str, s: Session = Depends(get_session)):
    row = s.get(ConfigEntry, name) if name in NAMES else None
    if row is None:
        raise HTTPException(404, "unknown config")
    return json.loads(row.data)


@router.put("/{name}", dependencies=[Depends(require_roles(ROLE_MANAGER))])
def put_config(name: str, body: Dict[str, Any], s: Session = Depends(get_session)):
    if name not in NAMES:
        raise HTTPException(404, "unknown config")
    row = s.get(ConfigEntry, name) or ConfigEntry(name=name, data="{}")
    row.data, row.updated_at = json.dumps(body, ensure_ascii=False), datetime.utcnow()
    s.add(row)
    s.commit()
    return body
