import pytest
from sqlmodel import SQLModel, create_engine

from app import db
from app.config import get_settings

SENDERS_CFG = {
    "match_threshold": 85,
    "senders": [
        {"name": "כללית", "aliases": ["שירותי בריאות כללית", "clalit"]},
        {"name": "מכבי", "aliases": ["מכבי שירותי בריאות", "maccabi"]},
        {"name": "שיבא", "aliases": ["המרכז הרפואי שיבא", "תל השומר"]},
    ],
}


@pytest.fixture
def senders_cfg():
    return SENDERS_CFG


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    """Isolated data dir and SQLite DB per test."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    db.set_engine(engine)
    SQLModel.metadata.create_all(engine)
    yield get_settings()
    db.set_engine(None)
    get_settings.cache_clear()


# ---------- auth ----------
# Route tests act as a logged-in user. By default the lab manager (who may do everything);
# `as_role("intake")` switches the current user, `no_auth_override` tests the real JWT path.

_TEST_USERS = {
    "lab_manager": ("manager_t", "Manager"),
    "intake": ("intake_t", "Intake"),
    "intake2": ("intake_t2", "Intake 2"),
    "approver": ("approver_t", "Approver"),
    "admin": ("admin_t", "Admin"),
}


def ensure_user(key: str):
    from sqlmodel import Session, select
    from app.models import User

    username, name = _TEST_USERS[key]
    role = "intake" if key.startswith("intake") else key
    with Session(db.get_engine()) as s:
        u = s.exec(select(User).where(User.username == username)).first()
        if u is None:
            u = User(username=username, display_name=name, role=role, roles=f'["{role}"]')
            s.add(u)
            s.commit()
            s.refresh(u)
        return u


@pytest.fixture(autouse=True)
def auth_user(request):
    from app.auth import get_current_user
    from app.main import app

    if "no_auth_override" in request.keywords or "tmp_env" not in request.fixturenames:
        yield None
        return
    request.getfixturevalue("tmp_env")
    current = {"key": "lab_manager"}
    app.dependency_overrides[get_current_user] = lambda: ensure_user(current["key"])
    yield current
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def as_role(auth_user):
    def switch(key: str):
        auth_user["key"] = key
        return ensure_user(key)
    return switch
