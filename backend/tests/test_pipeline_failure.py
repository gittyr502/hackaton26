"""The pipeline end to end with a stubbed Claude client: failures stay per-form, retry works,
and the confidence rules (empty / review / double-check) hold."""
import asyncio

from PIL import Image
from sqlmodel import Session, select

from app import db
from app.models import Batch, Field, Form, SourceFile
from pipeline.runner import build_context, process_batch, retry_form

GOOD = {
    "full_name": {"value": "דנה כהן", "confidence": 0.99, "legible": True},
    "id_number": {"value": "123456782", "confidence": 0.99, "legible": True},
    "central_numbers": {"value": ["A1", "A2"], "confidence": 0.95, "legible": True},
    "receipt_date": {"value": "05/03/2026", "confidence": 0.95, "legible": True},
    "sender": {"value": "מכבי", "confidence": 0.95, "legible": True},
    "commitment_numbers": {"value": ["555"], "confidence": 0.95, "legible": True},
}


class StubClient:
    def __init__(self, fail_first=0, response=None, second=None):
        self.fail_first = fail_first
        self.calls = 0
        self.response = response or GOOD
        self.second = second

    async def call_tool(self, image_b64, media_type, prompt, tool, system=None):
        if tool["name"] == "record_orientation":
            return {"clockwise_degrees": 0}
        self.calls += 1
        if self.calls <= self.fail_first:
            raise RuntimeError("boom")
        if self.second is not None and "Look again" in prompt:
            return self.second
        return self.response


def _make_batch(settings, n_files=2):
    up = settings.batches_dir / "1" / "uploads"
    up.mkdir(parents=True)
    with Session(db.get_engine()) as s:
        b = Batch()
        s.add(b)
        s.commit()
        s.refresh(b)
        for i in range(n_files):
            p = up / f"{i}.png"
            Image.new("RGB", (60, 80), "white").save(p)
            s.add(SourceFile(batch_id=b.id, filename=p.name, path=str(p)))
        s.commit()
        return b.id


def _ctx(settings, client, double_check=False):
    ctx = build_context(settings, client=client)
    ctx.senders_cfg = {"match_threshold": 85, "senders": [{"name": "מכבי", "aliases": []}]}
    ctx.pipeline_cfg = dict(ctx.pipeline_cfg, double_check={"enabled": double_check})
    return ctx


def _fields(form_id):
    with Session(db.get_engine()) as s:
        return {f.name: f for f in s.exec(select(Field).where(Field.form_id == form_id)).all()}


def test_failed_form_does_not_stop_batch_and_retry_works(tmp_env):
    batch_id = _make_batch(tmp_env)
    asyncio.run(process_batch(batch_id, _ctx(tmp_env, StubClient(fail_first=1))))

    with Session(db.get_engine()) as s:
        forms = s.exec(select(Form)).all()
        assert sorted(f.status for f in forms) == ["done", "failed"]
        assert all(sf.status == "done" for sf in s.exec(select(SourceFile)).all())
        assert s.get(Batch, batch_id).status == "done"
        failed = next(f for f in forms if f.status == "failed")

    asyncio.run(retry_form(failed.id, _ctx(tmp_env, StubClient())))
    with Session(db.get_engine()) as s:
        assert s.get(Form, failed.id).status == "done"
    fields = _fields(failed.id)
    assert len(fields) == 6
    assert all(f.level == "ok" for f in fields.values())
    assert fields["receipt_date"].value == '"2026-03-05"'


def test_levels_null_is_empty_bad_id_is_review(tmp_env):
    resp = dict(GOOD, full_name={"value": None, "confidence": 0.2, "legible": False},
                id_number={"value": "123456789", "confidence": 0.99, "legible": True})
    batch_id = _make_batch(tmp_env, n_files=1)
    asyncio.run(process_batch(batch_id, _ctx(tmp_env, StubClient(response=resp))))
    with Session(db.get_engine()) as s:
        form = s.exec(select(Form)).one()
    f = _fields(form.id)
    assert f["full_name"].level == "empty" and f["full_name"].value is None
    assert f["id_number"].level == "review"
    assert "invalid_id_checksum" in f["id_number"].reasons


def test_double_check_upgrades_soft_only(tmp_env):
    resp = dict(GOOD,
                full_name={"value": "דנה כהן", "confidence": 0.5, "legible": True},          # soft only
                id_number={"value": "123456789", "confidence": 0.5, "legible": True})    # validation
    second = {"full_name": {"value": "דנה כהן", "confidence": 0.9, "legible": True}}
    client = StubClient(response=resp, second=second)
    batch_id = _make_batch(tmp_env, n_files=1)
    asyncio.run(process_batch(batch_id, _ctx(tmp_env, client, double_check=True)))
    with Session(db.get_engine()) as s:
        form = s.exec(select(Form)).one()
    f = _fields(form.id)
    assert f["full_name"].level == "ok"
    assert "double_check_confirmed" in f["full_name"].reasons
    assert f["id_number"].level == "review"  # validation failure never upgraded


def test_double_check_disagreement_stays_review(tmp_env):
    resp = dict(GOOD, full_name={"value": "דנה כהן", "confidence": 0.5, "legible": True})
    second = {"full_name": {"value": "דנה כחן", "confidence": 0.9, "legible": True}}
    batch_id = _make_batch(tmp_env, n_files=1)
    asyncio.run(process_batch(batch_id, _ctx(tmp_env, StubClient(response=resp, second=second),
                                             double_check=True)))
    with Session(db.get_engine()) as s:
        form = s.exec(select(Form)).one()
    f = _fields(form.id)
    assert f["full_name"].level == "review"
    assert "double_check_disagree" in f["full_name"].reasons


def test_stored_page_image_is_the_one_the_stages_left_on_disk(tmp_env):
    """Orientation may rotate the page file; the viewer must get that same image back."""
    batch_id = _make_batch(tmp_env, n_files=1)

    class Rotating(StubClient):
        async def call_tool(self, image_b64, media_type, prompt, tool, system=None):
            if tool["name"] == "record_orientation":
                return {"clockwise_degrees": 90}
            return await super().call_tool(image_b64, media_type, prompt, tool, system)

    asyncio.run(process_batch(batch_id, _ctx(tmp_env, Rotating())))
    with Session(db.get_engine()) as s:
        import io
        form = s.exec(select(Form)).one()
        assert Image.open(io.BytesIO(form.image_data)).size == (80, 60)  # the 60x80 source, turned
