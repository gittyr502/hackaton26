from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.config import get_settings

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        s = get_settings()
        s.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{s.db_path}", connect_args={"check_same_thread": False}
        )
    return _engine


def set_engine(engine) -> None:
    """For tests: swap in an in-memory engine."""
    global _engine
    _engine = engine


def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(get_engine())
    _add_missing_columns()
    seed_config()
    migrate_config()
    backfill_blobs()
    seed_users()
    backfill_workflow()


def _add_missing_columns() -> None:
    """create_all never alters existing tables: add columns introduced after a DB was created."""
    new_columns = {
        "field": {"box": "TEXT"},
        "batch": {"started_at": "DATETIME", "finished_at": "DATETIME", "uploaded_by": "INTEGER"},
        "sourcefile": {"content": "BLOB"},
        "form": {"image_data": "BLOB", "workflow": "VARCHAR", "assigned_to": "INTEGER",
                 "approver_comment": "VARCHAR", "created_at": "DATETIME"},
    }
    with get_engine().begin() as conn:
        for table, cols in new_columns.items():
            have = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            for name, ddl in cols.items():
                if name not in have:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def seed_config() -> None:
    """Copy config/*.yaml into the DB the first time (afterwards the DB is the source of truth)."""
    import json
    from app.models import ConfigEntry

    s = get_settings()
    with Session(get_engine()) as session:
        for name in ("export", "senders", "pipeline"):
            if session.get(ConfigEntry, name) is None:
                session.add(ConfigEntry(name=name, data=json.dumps(s._yaml(f"{name}.yaml"), ensure_ascii=False)))
        session.commit()


def migrate_config() -> None:
    """Stored export layouts from before full_name: first_name/last_name columns become one full_name column."""
    import json
    from app.models import ConfigEntry

    with Session(get_engine()) as session:
        row = session.get(ConfigEntry, "export")
        if row is None:
            return
        data = json.loads(row.data or "{}")
        columns = data.get("columns") or []
        old = {"first_name", "last_name"}
        if not any(c.get("field") in old for c in columns):
            return
        out = []
        for c in columns:
            if c.get("field") in old:
                if not any(o.get("field") == "full_name" for o in out):
                    out.append({"field": "full_name", "header": "שם מלא"})
            else:
                out.append(c)
        data["columns"] = out
        row.data = json.dumps(data, ensure_ascii=False)
        session.add(row)
        session.commit()


def backfill_blobs() -> None:
    """Files and page images of batches created before blobs lived in the DB: read them from disk once."""
    from pathlib import Path
    from sqlmodel import select
    from app.models import Form, SourceFile

    with Session(get_engine()) as session:
        for sf in session.exec(select(SourceFile).where(SourceFile.content == None)).all():  # noqa: E711
            if sf.path and Path(sf.path).is_file():
                sf.content = Path(sf.path).read_bytes()
                session.add(sf)
        for fm in session.exec(select(Form).where(Form.image_data == None)).all():  # noqa: E711
            if fm.image_path and Path(fm.image_path).is_file():
                fm.image_data = Path(fm.image_path).read_bytes()
                session.add(fm)
        session.commit()


DEMO_USERS = [
    ("intake1", "רותי כהן", "intake"),
    ("intake2", "דנה מזרחי", "intake"),
    ("approver1", "יעל לוי", "approver"),
    ("manager1", "ד״ר מיכל לוי", "lab_manager"),
]


def seed_users() -> None:
    """First run: one demo user per role (password DEMO_PASSWORD from .env)."""
    from sqlmodel import select
    from app.auth import hash_password
    from app.models import User

    with Session(get_engine()) as session:
        if session.exec(select(User.id)).first() is not None:
            return
        pw = get_settings().demo_password
        for username, name, role in DEMO_USERS:
            session.add(User(username=username, display_name=name, role=role, password_hash=hash_password(pw)))
        session.commit()


def backfill_workflow() -> None:
    """Forms finished before the approval workflow existed get the same starting state as new ones."""
    from sqlmodel import select
    from app.models import Field, Form
    from app.workflow import initial_workflow

    with get_engine().begin() as conn:  # forms from before created_at existed: use their batch's time
        conn.exec_driver_sql(
            "UPDATE form SET created_at = (SELECT created_at FROM batch WHERE batch.id = form.batch_id) "
            "WHERE created_at IS NULL"
        )
    with Session(get_engine()) as session:
        forms = session.exec(select(Form).where(Form.status == "done", Form.workflow == None)).all()  # noqa: E711
        for fm in forms:
            levels = session.exec(select(Field.level).where(Field.form_id == fm.id)).all()
            fm.workflow = initial_workflow(levels)
            session.add(fm)
        session.commit()


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
