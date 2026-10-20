"""Login, JWT and role checks. Passwords are pbkdf2 (stdlib); tokens are HS256 JWTs signed with JWT_SECRET.

A user may hold several roles (User.roles); every check asks "does the user have one of these roles".
"""
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

import jwt
from fastapi import Depends, HTTPException, Query, Request
from sqlmodel import Session

from app.config import get_settings
from app.db import get_session
from app.models import Batch, Form, User

ROLE_INTAKE = "intake"
ROLE_APPROVER = "approver"
ROLE_MANAGER = "lab_manager"
ROLE_ADMIN = "admin"  # manages users; does not inherit lab_manager (give both roles to someone who needs both)
ROLES = (ROLE_INTAKE, ROLE_APPROVER, ROLE_MANAGER, ROLE_ADMIN)
ROLE_PRIORITY = (ROLE_ADMIN, ROLE_MANAGER, ROLE_APPROVER, ROLE_INTAKE)  # primary role = first one held

# What each role may do: shown to the admin (read-only); the routes enforce it with require_roles.
ROLE_PERMISSIONS: Dict[str, List[str]] = {
    ROLE_INTAKE: ["upload", "fix_fields", "submit", "patients"],
    ROLE_APPROVER: ["approve", "return", "comment", "patients"],
    ROLE_MANAGER: ["view_all", "dashboards", "export", "assign", "settings", "rules", "patients"],
    ROLE_ADMIN: ["users", "rules", "audit", "patients"],
}


def roles_of(user: User) -> List[str]:
    try:
        roles = [r for r in json.loads(user.roles or "[]") if r in ROLES]
    except (ValueError, TypeError):
        roles = []
    return roles or [user.role]


def has_role(user: User, *roles: str) -> bool:
    return any(r in roles for r in roles_of(user))


def primary_role(roles: List[str]) -> str:
    return next((r for r in ROLE_PRIORITY if r in roles), ROLE_INTAKE)

_ITERATIONS = 200_000
_fallback_secret = secrets.token_hex(32)  # no JWT_SECRET: tokens are valid until the server restarts


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, digest = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), digest)


def _secret() -> str:
    return get_settings().jwt_secret or _fallback_secret


def create_token(user: User, ttl: Optional[timedelta] = None) -> str:
    ttl = ttl if ttl is not None else timedelta(hours=get_settings().jwt_ttl_hours)
    payload = {"sub": str(user.id), "role": user.role, "tv": user.token_version or 0,
               "exp": datetime.now(timezone.utc) + ttl}
    return jwt.encode(payload, _secret(), algorithm="HS256")


def user_dict(user: User) -> dict:
    return {"id": user.id, "username": user.username, "display_name": user.display_name, "role": user.role,
            "roles": roles_of(user), "active": bool(user.active)}


def get_current_user(
    request: Request,
    token: Optional[str] = Query(None, include_in_schema=False),  # <img src> cannot send headers
    s: Session = Depends(get_session),
) -> User:
    header = request.headers.get("authorization", "")
    raw = header[7:] if header.lower().startswith("bearer ") else token
    if not raw:
        raise HTTPException(401, "not authenticated")
    try:
        payload = jwt.decode(raw, _secret(), algorithms=["HS256"])
        user = s.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "invalid or expired token")
    if user is None or not user.active:
        raise HTTPException(401, "user not found")
    if int(payload.get("tv", 0)) != (user.token_version or 0):  # password reset / role change / deactivation
        raise HTTPException(401, "token revoked")
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    def dep(user: User = Depends(get_current_user)) -> User:
        if not has_role(user, *roles):
            raise HTTPException(403, "not allowed for this role")
        return user

    return dep


# ---------- ownership ----------

def can_view_batch(s: Session, user: User, batch: Batch) -> bool:
    if has_role(user, ROLE_APPROVER, ROLE_MANAGER):
        return True
    if not has_role(user, ROLE_INTAKE):
        return False
    if batch.uploaded_by == user.id:
        return True
    from sqlmodel import select

    return s.exec(select(Form.id).where(Form.batch_id == batch.id, Form.assigned_to == user.id)).first() is not None


def check_batch_view(s: Session, user: User, batch: Batch) -> None:
    if not can_view_batch(s, user, batch):
        raise HTTPException(404, "batch not found")  # do not reveal other clerks' batches


def check_batch_owner(user: User, batch: Batch) -> None:
    """pause / resume / cancel / delete: the uploading clerk or the lab manager."""
    if has_role(user, ROLE_MANAGER) or (has_role(user, ROLE_INTAKE) and batch.uploaded_by == user.id):
        return
    raise HTTPException(403, "not allowed for this batch")


def check_form_editor(s: Session, user: User, form: Form) -> None:
    """Editing fields / retrying: the assigned clerk (or the uploader when unassigned) or the lab manager."""
    if has_role(user, ROLE_MANAGER):
        return
    if has_role(user, ROLE_INTAKE):
        owner = form.assigned_to
        if owner is None:
            batch = s.get(Batch, form.batch_id)
            owner = batch.uploaded_by if batch else None
        if owner is None or owner == user.id:
            return
    raise HTTPException(403, "not allowed to edit this form")
