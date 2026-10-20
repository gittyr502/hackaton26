"""Login, JWT and role checks on the real auth path (no test-user override)."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import db
from app.auth import create_token, hash_password, verify_password
from app.main import app
from app.models import Batch, Form, SourceFile, User

pytestmark = pytest.mark.no_auth_override


def _login(client, username, password="demo1234"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_password_hash_roundtrip():
    h = hash_password("s3cret")
    assert h.startswith("pbkdf2_sha256$") and "s3cret" not in h
    assert verify_password("s3cret", h)
    assert not verify_password("wrong", h)
    assert not verify_password("s3cret", "garbage")


def test_demo_users_login_and_me(tmp_env):
    with TestClient(app) as client:
        assert _login(client, "intake1", "nope").status_code == 401
        assert _login(client, "nobody").status_code == 401
        r = _login(client, "approver1")
        assert r.status_code == 200
        body = r.json()
        assert body["user"]["role"] == "approver" and "password_hash" not in body["user"]
        me = client.get("/api/auth/me", headers=_bearer(body["token"]))
        assert me.status_code == 200 and me.json()["username"] == "approver1"


def test_missing_bad_and_expired_token(tmp_env):
    with TestClient(app) as client:
        assert client.get("/api/batches").status_code == 401
        assert client.get("/api/batches", headers=_bearer("not-a-jwt")).status_code == 401
        with Session(db.get_engine()) as s:
            user = s.get(User, 1)
            expired = create_token(user, ttl=timedelta(seconds=-5))
        assert client.get("/api/batches", headers=_bearer(expired)).status_code == 401


def test_roles_are_enforced(tmp_env):
    with TestClient(app) as client:
        approver = _bearer(_login(client, "approver1").json()["token"])
        intake = _bearer(_login(client, "intake1").json()["token"])
        manager = _bearer(_login(client, "manager1").json()["token"])
        assert client.get("/api/dashboard/backlog", headers=intake).status_code == 403
        assert client.get("/api/dashboard/backlog", headers=manager).status_code == 200
        assert client.get("/api/users", headers=approver).status_code == 403
        assert client.put("/api/config/senders", json={}, headers=intake).status_code == 403
        files = {"files": ("a.png", b"x", "image/png")}
        assert client.post("/api/batches", files=files, headers=approver).status_code == 403


def test_image_accepts_token_query(tmp_env):
    with Session(db.get_engine()) as s:
        b = Batch(status="done")
        s.add(b)
        s.commit()
        sf = SourceFile(batch_id=b.id, filename="a.png", path="a.png", status="done")
        s.add(sf)
        s.commit()
        fm = Form(batch_id=b.id, source_file_id=sf.id, status="done", image_data=b"\x89PNG")
        s.add(fm)
        s.commit()
        form_id = fm.id
    with TestClient(app) as client:
        token = _login(client, "manager1").json()["token"]
        assert client.get(f"/api/forms/{form_id}/image").status_code == 401
        r = client.get(f"/api/forms/{form_id}/image?token={token}")
        assert r.status_code == 200 and r.content == b"\x89PNG"


def _empty_users():
    from sqlmodel import delete

    with Session(db.get_engine()) as s:
        s.exec(delete(User))
        s.commit()


def test_builtin_manager_only_when_no_users(tmp_env):
    with TestClient(app) as client:
        # demo users exist: the fixed manager is refused
        assert _login(client, "manager", "Manager2024!").status_code == 401
        _empty_users()
        assert _login(client, "manager", "wrong").status_code == 401
        r = _login(client, "manager", "Manager2024!")
        assert r.status_code == 200 and set(r.json()["user"]["roles"]) == {"lab_manager", "admin"}
        headers = _bearer(r.json()["token"])
        assert client.get("/api/auth/me", headers=headers).json()["username"] == "manager"
        assert client.get("/api/dashboard/backlog", headers=headers).status_code == 200
        assert client.get("/api/admin/roles", headers=headers).status_code == 200


def test_builtin_manager_needs_no_db_user_lookup(tmp_env):
    with TestClient(app) as client:
        _empty_users()
        headers = _bearer(_login(client, "manager", "Manager2024!").json()["token"])
        with Session(db.get_engine()) as s:  # the token keeps working with the users table empty
            assert s.get(User, 1) is None
        assert client.get("/api/auth/me", headers=headers).status_code == 200
