from datetime import datetime
from typing import Optional

from sqlalchemy import Column, LargeBinary
from sqlmodel import Field as SQLField, SQLModel


class Batch(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
    status: str = "processing"  # processing | done
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    uploaded_by: Optional[int] = SQLField(default=None, foreign_key="user.id", index=True)


class SourceFile(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    batch_id: int = SQLField(foreign_key="batch.id", index=True)
    filename: str
    path: str
    mime: str = ""
    status: str = "pending"  # pending | processing | done | failed
    progress: float = 0.0  # 0..1
    error: Optional[str] = None
    content: Optional[bytes] = SQLField(default=None, sa_column=Column(LargeBinary))  # the uploaded file itself


class Form(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    batch_id: int = SQLField(foreign_key="batch.id", index=True)
    source_file_id: int = SQLField(foreign_key="sourcefile.id", index=True)
    page_index: int = 0
    image_path: str = ""  # working copy on disk while the batch is processed
    image_data: Optional[bytes] = SQLField(default=None, sa_column=Column(LargeBinary))  # page image (PNG)
    status: str = "pending"  # pending | processing | done | failed  (pipeline state)
    error: Optional[str] = None
    # approval workflow, set once the pipeline is done: needs_fix | pending_approval | returned | approved
    workflow: Optional[str] = SQLField(default=None, index=True)
    assigned_to: Optional[int] = SQLField(default=None, foreign_key="user.id", index=True)
    approver_comment: Optional[str] = None
    created_at: datetime = SQLField(default_factory=datetime.utcnow)


class Field(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    form_id: int = SQLField(foreign_key="form.id", index=True)
    name: str
    value: Optional[str] = None  # JSON-encoded (str or list[str]) or None
    raw_value: Optional[str] = None
    confidence: float = 0.0
    level: str = "empty"  # ok | review | empty
    reasons: str = "[]"  # JSON list of {kind, code}
    manually_corrected: bool = False
    box: Optional[str] = None  # JSON [x0, y0, x1, y1], fractions of the page image


class ExportSetting(SQLModel, table=True):
    """The export options chosen for a batch (the password is never stored)."""
    batch_id: int = SQLField(foreign_key="batch.id", primary_key=True)
    format: str = "xlsx"  # xlsx | csv | json
    include_details: bool = True  # confidence sheet
    include_source_links: bool = True  # link to the scanned page next to every row
    password_protect: bool = False


class ExportRecord(SQLModel, table=True):
    """One row per downloaded export file (metadata only, the file itself is not kept)."""
    id: Optional[int] = SQLField(default=None, primary_key=True)
    batch_id: int = SQLField(foreign_key="batch.id", index=True)
    created_at: datetime = SQLField(default_factory=datetime.utcnow)
    format: str
    filename: str
    size_bytes: int
    sha256: str
    rows: int = 0
    protected: bool = False


class ConfigEntry(SQLModel, table=True):
    """Mappings and layouts (export columns, sender aliases, pipeline) kept in the DB; seeded from config/*.yaml."""
    name: str = SQLField(primary_key=True)  # export | senders | pipeline
    data: str  # JSON
    updated_at: datetime = SQLField(default_factory=datetime.utcnow)


class User(SQLModel, table=True):
    id: Optional[int] = SQLField(default=None, primary_key=True)
    username: str = SQLField(index=True, sa_column_kwargs={"unique": True})
    display_name: str = ""
    role: str = "intake"  # intake | approver | lab_manager
    password_hash: str = ""
    active: bool = True


class AuditLog(SQLModel, table=True):
    """Who changed what and when: every workflow transition and field mutation (values live in the DB, never in logs)."""
    id: Optional[int] = SQLField(default=None, primary_key=True)
    at: datetime = SQLField(default_factory=datetime.utcnow, index=True)
    user_id: Optional[int] = SQLField(default=None, foreign_key="user.id", index=True)
    action: str = SQLField(index=True)  # status_change | field_corrected | field_approved | field_reset | assigned
    entity: str  # form | field | batch
    entity_id: int = SQLField(index=True)
    form_id: Optional[int] = SQLField(default=None, index=True)  # the form the entity belongs to
    before: Optional[str] = None  # JSON
    after: Optional[str] = None  # JSON
    comment: Optional[str] = None
