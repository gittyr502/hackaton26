"""Runs source files through the stages in pipeline.yaml and persists results."""
import asyncio
import importlib
import inspect
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from sqlmodel import Session, select

from app import audit
from app.config import Settings, get_settings
from app.db import get_engine
from app.logging_utils import get_logger, log_event
from app.models import Batch, Field, Form, SourceFile
from app.workflow import initial_workflow
from pipeline import control
from pipeline.base import Context, FormDoc

log = get_logger("runner")


def load_stages(pipeline_cfg: Dict[str, Any]) -> List[Any]:
    stages = []
    for spec in pipeline_cfg["stages"]:
        module_name, cls_name = spec.split(":")
        cls = getattr(importlib.import_module(module_name), cls_name)
        stages.append(cls())
    return stages


def build_context(settings: Optional[Settings] = None, client: Any = None,
                  batch_dir: Optional[Path] = None) -> Context:
    s = settings or get_settings()
    pcfg = s.pipeline
    if client is None:
        from pipeline.claude_client import ClaudeClient

        ex = pcfg.get("extract", {})
        client = ClaudeClient(
            api_key=s.anthropic_api_key,
            ssl_cert_file=s.ssl_cert_file,
            model=s.claude_model,
            concurrency=ex.get("concurrency", 5),
            max_retries=ex.get("max_retries", 4),
            base_delay=ex.get("base_delay_seconds", 1.0),
            max_tokens=ex.get("max_tokens", 2048),
        )
    return Context(settings=s, pipeline_cfg=pcfg, senders_cfg=s.senders,
                   client=client, batch_dir=batch_dir)


async def run_stage(stage: Any, doc: FormDoc, ctx: Context) -> List[FormDoc]:
    if inspect.iscoroutinefunction(stage.run):
        out = await stage.run(doc, ctx)
    else:
        out = await asyncio.to_thread(stage.run, doc, ctx)
    return out if isinstance(out, list) else [out]


# ---------- persistence helpers (short sync sessions) ----------

def _session() -> Session:
    return Session(get_engine())


def _update(model, obj_id: int, **values) -> None:
    with _session() as s:
        obj = s.get(model, obj_id)
        if obj is None:
            return
        for k, v in values.items():
            setattr(obj, k, v)
        s.add(obj)
        s.commit()


def _create_form(doc: FormDoc) -> int:
    image = Path(doc.image_path)
    with _session() as s:
        form = Form(batch_id=doc.batch_id, source_file_id=doc.source_file_id,
                    page_index=doc.page_index, image_path=doc.image_path, status="processing",
                    image_data=image.read_bytes() if image.is_file() else None)
        s.add(form)
        s.commit()
        s.refresh(form)
        return form.id


def _dump(v: Any) -> Optional[str]:
    return None if v is None else json.dumps(v, ensure_ascii=False)


def save_fields(form_id: int, doc: FormDoc) -> None:
    with _session() as s:
        for old in s.exec(select(Field).where(Field.form_id == form_id)).all():
            s.delete(old)
        for name, fr in doc.fields.items():
            s.add(Field(
                form_id=form_id, name=name, value=_dump(fr.value), raw_value=_dump(fr.raw_value),
                confidence=fr.confidence, level=fr.level, box=_dump(fr.box), box_verified=fr.box_verified,
                reasons=json.dumps(fr.reasons, ensure_ascii=False),
            ))
        form = s.get(Form, form_id)
        form.status, form.error = "done", None
        if doc.image_path and Path(doc.image_path).is_file():
            form.image_data = Path(doc.image_path).read_bytes()  # the page may have been turned upright
        before = form.workflow
        form.workflow = initial_workflow(fr.level for fr in doc.fields.values())
        form.approver_comment = None
        if form.assigned_to is None:
            batch = s.get(Batch, form.batch_id)
            form.assigned_to = batch.uploaded_by if batch else None
        s.add(form)
        audit.record(s, None, "status_change", "form", form_id,
                     before={"workflow": before}, after={"workflow": form.workflow})
        s.commit()


# ---------- execution ----------

ProgressFn = Optional[Callable[[int], None]]


async def run_docs(stages: List[Any], docs: List[FormDoc], ctx: Context,
                   on_progress: ProgressFn = None, start: int = 0,
                   persist: bool = True, results: Optional[List[FormDoc]] = None) -> None:
    """Run docs through stages[start:], fanning out on list results.

    Each form fails independently. A failure before a form exists (e.g. an
    unreadable file) is re-raised so the caller can mark the source file failed.
    on_progress(n): n > 0 announces a fan-out into n forms; n == 0 means one form finished.
    """
    n = len(stages)

    async def run_one(doc: FormDoc, idx: int) -> None:
        try:
            for i in range(idx, n):
                await control.checkpoint(doc.batch_id)
                outs = await run_stage(stages[i], doc, ctx)
                if persist:
                    for o in outs:
                        if o.image_path and o.form_id is None:
                            o.form_id = _create_form(o)
                if len(outs) != 1:
                    if on_progress:
                        on_progress(len(outs))
                    await asyncio.gather(*(run_one(o, i + 1) for o in outs))
                    return
                doc = outs[0]
            if persist and doc.form_id is not None:
                save_fields(doc.form_id, doc)
                log_event(log, "form_done", form_id=doc.form_id)
            if results is not None:
                results.append(doc)
            if on_progress:
                on_progress(0)
        except control.BatchCancelled:
            if persist and doc.form_id is not None:
                _update(Form, doc.form_id, status="failed", error="בוטל על ידי המשתמש")
            raise
        except Exception as e:
            log_event(log, "form_failed", form_id=doc.form_id,
                      source_file_id=doc.source_file_id, error=type(e).__name__)
            if persist and doc.form_id is not None:
                _update(Form, doc.form_id, status="failed",
                        error=f"{type(e).__name__}: {e}"[:500])
                if on_progress:
                    on_progress(0)
            elif doc.image_path and results is not None:
                doc.form_type = "__failed__"
                results.append(doc)
            else:
                raise

    await asyncio.gather(*(run_one(d, start) for d in docs))


async def process_source_file(sf_id: int, batch_id: int, stages: List[Any], ctx: Context) -> None:
    with _session() as s:
        path = s.get(SourceFile, sf_id).path
    _update(SourceFile, sf_id, status="processing", progress=0.0)
    state = {"total": 1, "done": 0}

    def on_progress(fanout: int) -> None:
        if fanout:
            state["total"] = fanout
        else:
            state["done"] += 1
        _update(SourceFile, sf_id, progress=min(state["done"] / max(state["total"], 1), 1.0))

    doc = FormDoc(batch_id=batch_id, source_file_id=sf_id, file_path=path)
    try:
        await run_docs(stages, [doc], ctx, on_progress)
        _update(SourceFile, sf_id, status="done", progress=1.0)
        log_event(log, "file_done", source_file_id=sf_id)
    except control.BatchCancelled:
        _update(SourceFile, sf_id, status="failed", error="בוטל על ידי המשתמש")
        log_event(log, "file_cancelled", source_file_id=sf_id)
    except Exception as e:
        log_event(log, "file_failed", source_file_id=sf_id, error=type(e).__name__)
        _update(SourceFile, sf_id, status="failed", error=f"{type(e).__name__}: {e}"[:500])


async def process_batch(batch_id: int, ctx: Optional[Context] = None) -> None:
    settings = get_settings()
    ctx = ctx or build_context(settings)
    if ctx.batch_dir is None:
        ctx.batch_dir = settings.batches_dir / str(batch_id)
    stages = load_stages(ctx.pipeline_cfg)
    _update(Batch, batch_id, started_at=datetime.utcnow())
    with _session() as s:
        sf_ids = [sf.id for sf in s.exec(select(SourceFile).where(SourceFile.batch_id == batch_id)).all()]
    log_event(log, "batch_start", batch_id=batch_id, files=len(sf_ids))
    await asyncio.gather(*(process_source_file(i, batch_id, stages, ctx) for i in sf_ids))
    _update(Batch, batch_id, status="done", finished_at=datetime.utcnow())
    control.clear(batch_id)
    _drop_working_files(ctx.batch_dir)
    log_event(log, "batch_done", batch_id=batch_id)


def _drop_working_files(batch_dir: Optional[Path]) -> None:
    """Everything is kept in the DB; the on-disk copies are scratch space for the pipeline only."""
    if batch_dir:
        shutil.rmtree(batch_dir, ignore_errors=True)


def _restore_image(form_id: int) -> None:
    """Write the page image from the DB back to its working path so the stages can read it."""
    with _session() as s:
        form = s.get(Form, form_id)
        if form and form.image_data and form.image_path and not Path(form.image_path).is_file():
            Path(form.image_path).parent.mkdir(parents=True, exist_ok=True)
            Path(form.image_path).write_bytes(form.image_data)


async def retry_form(form_id: int, ctx: Optional[Context] = None) -> None:
    settings = get_settings()
    with _session() as s:
        form = s.get(Form, form_id)
        doc = FormDoc(batch_id=form.batch_id, source_file_id=form.source_file_id, form_id=form.id,
                      page_index=form.page_index, image_path=form.image_path)
        batch_id = form.batch_id
    ctx = ctx or build_context(settings)
    if ctx.batch_dir is None:
        ctx.batch_dir = settings.batches_dir / str(batch_id)
    stages = load_stages(ctx.pipeline_cfg)
    names = [type(st).__name__.lower() for st in stages]
    start = names.index(ctx.pipeline_cfg.get("retry_from", "classify"))
    _restore_image(form_id)
    _update(Form, form_id, status="processing", error=None, workflow=None)  # re-entered when it finishes
    log_event(log, "form_retry", form_id=form_id)
    try:
        await run_docs(stages, [doc], ctx, start=start)
    finally:
        Path(doc.image_path).unlink(missing_ok=True)
