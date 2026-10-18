"""Pipeline building blocks: FormDoc (working object), Context, Stage protocol."""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Union

from pydantic import BaseModel, Field as PField

from app.config import Settings


class FieldResult(BaseModel):
    value: Any = None  # str | list[str] | None
    raw_value: Any = None
    confidence: float = 0.0
    legible: bool = True
    handwritten: bool = False
    box: Optional[List[float]] = None  # normalized [x0, y0, x1, y1] on the page image
    level: str = "empty"
    reasons: List[Dict[str, str]] = PField(default_factory=list)

    def add_reason(self, kind: str, code: str) -> None:
        if not any(r["code"] == code for r in self.reasons):
            self.reasons.append({"kind": kind, "code": code})


class FormDoc(BaseModel):
    batch_id: int
    source_file_id: int
    form_id: Optional[int] = None
    file_path: str = ""  # original upload (or converted copy)
    mime: str = ""
    pages: List[str] = PField(default_factory=list)  # rendered page images (pre-split)
    page_index: int = 0
    image_path: str = ""  # this form's page image (post-split)
    form_type: Optional[str] = None
    fields: Dict[str, FieldResult] = PField(default_factory=dict)


@dataclass
class Context:
    settings: Settings
    pipeline_cfg: Dict[str, Any]
    senders_cfg: Dict[str, Any]
    client: Any  # pipeline.claude_client.ClaudeClient (or a test stub)
    batch_dir: Any = None
    extras: Dict[str, Any] = field(default_factory=dict)


StageResult = Union[FormDoc, List[FormDoc]]


class Stage(Protocol):
    """A pipeline stage. `run` may be sync or async; returning a list fans out."""

    def run(self, form: FormDoc, ctx: Context) -> StageResult: ...
