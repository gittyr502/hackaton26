"""Speed (roadmap 2ד): adaptive concurrency, model per stage, prompt caching, JPEG crops."""
import asyncio
import base64
import io
from types import SimpleNamespace

import anthropic
import httpx
from PIL import Image

from pipeline.base import Context
from pipeline.claude_client import AdaptiveLimiter, ClaudeClient
from pipeline.crops import crop_b64, halves_b64

TOOL = {"name": "record_form", "description": "d", "input_schema": {"type": "object", "properties": {}}}
TOOL_REPLY = SimpleNamespace(content=[SimpleNamespace(type="tool_use", name="record_form", input={"ok": 1})])


def _rate_limited(retry_after=None):
    headers = {"retry-after": str(retry_after)} if retry_after is not None else {}
    resp = httpx.Response(429, headers=headers, request=httpx.Request("POST", "https://x"))
    return anthropic.RateLimitError("slow down", response=resp, body=None)


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def make_client(replies, **kw):
    client = ClaudeClient(api_key="test", model="opus", max_retries=3, base_delay=0, **kw)
    fake = FakeMessages(replies)
    client._client = SimpleNamespace(messages=fake)
    return client, fake


def test_limiter_halves_on_rate_limit_and_grows_back():
    lim = AdaptiveLimiter(16, adaptive=True, grow_after=2)
    lim.on_rate_limit()
    assert lim.limit == 8
    lim.on_rate_limit()
    lim.on_rate_limit()
    lim.on_rate_limit()
    assert lim.limit == 2  # never below the minimum
    for _ in range(4):
        lim.on_success()
    assert lim.limit == 4


def test_limiter_without_adaptive_keeps_its_limit():
    lim = AdaptiveLimiter(5)
    lim.on_rate_limit()
    assert lim.limit == 5


def test_limiter_caps_parallel_calls():
    lim = AdaptiveLimiter(3)
    peak = {"now": 0, "max": 0}

    async def work():
        await lim.acquire()
        peak["now"] += 1
        peak["max"] = max(peak["max"], peak["now"])
        await asyncio.sleep(0.01)
        peak["now"] -= 1
        await lim.release()

    async def main():
        await asyncio.gather(*(work() for _ in range(12)))

    asyncio.run(main())
    assert peak["max"] == 3


def test_rate_limit_lowers_concurrency_and_retries():
    client, fake = make_client([_rate_limited(), TOOL_REPLY], concurrency=16, adaptive=True)
    assert asyncio.run(client.call_tool("b64", "image/jpeg", "p", TOOL)) == {"ok": 1}
    assert client.limiter.limit == 8
    assert len(fake.calls) == 2


def test_model_override_and_cache_control():
    client, fake = make_client([TOOL_REPLY, TOOL_REPLY])
    asyncio.run(client.call_tool("b64", "image/jpeg", "p", TOOL, system="S", model="haiku"))
    asyncio.run(client.call_tool("b64", "image/jpeg", "p", TOOL, system="S"))
    assert fake.calls[0]["model"] == "haiku"
    assert fake.calls[1]["model"] == "opus"
    assert fake.calls[0]["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert fake.calls[0]["tools"][-1]["cache_control"] == {"type": "ephemeral"}


def test_text_only_call_sends_no_image():
    client, fake = make_client([TOOL_REPLY])
    asyncio.run(client.call_tool_text("rule text", TOOL, system="S"))
    content = fake.calls[0]["messages"][0]["content"]
    assert [c["type"] for c in content] == ["text"]


class ModelAwareStub:
    def __init__(self):
        self.models = []

    async def call_tool(self, image_b64, media_type, prompt, tool, system=None, model=None):
        self.models.append(model)
        return {}


class PlainStub:
    async def call_tool(self, image_b64, media_type, prompt, tool, system=None):
        return {"plain": True}


def _stage_ctx(client, models):
    return Context(settings=None, pipeline_cfg={}, senders_cfg={}, client=client, models=models)


def test_context_routes_model_per_stage():
    stub = ModelAwareStub()
    ctx = _stage_ctx(stub, {"classify": "haiku", "extract": None})
    kw = dict(image_b64="x", media_type="image/jpeg", prompt="p", tool=TOOL)
    asyncio.run(ctx.call_tool("classify", **kw))
    asyncio.run(ctx.call_tool("extract", **kw))
    asyncio.run(ctx.call_tool("unknown", **kw))
    assert stub.models == ["haiku", None, None]


def test_context_keeps_old_stubs_working():
    ctx = _stage_ctx(PlainStub(), {"classify": "haiku"})
    got = asyncio.run(ctx.call_tool("classify", image_b64="x", media_type="image/jpeg", prompt="p", tool=TOOL))
    assert got == {"plain": True}


def _decode(b64):
    return Image.open(io.BytesIO(base64.b64decode(b64)))


def test_crops_are_jpeg_and_capped(tmp_path):
    page = tmp_path / "p.png"
    Image.new("RGB", (5000, 7000), "white").save(page)
    crop = _decode(crop_b64(str(page), [0.0, 0.0, 1.0, 1.0]))
    assert crop.format == "JPEG"
    assert max(crop.size) <= 1568
    assert all(max(_decode(h).size) <= 1568 for h in halves_b64(str(page)))


# ---------- early save: reviewable before the background checks end ----------

from sqlalchemy import event  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from app import db, events  # noqa: E402
from app.api.serialize import batch_detail  # noqa: E402
from app.models import Batch, Field, Form  # noqa: E402
from pipeline.runner import process_batch  # noqa: E402
from tests.test_pipeline_failure import GOOD, StubClient, _ctx, _make_batch  # noqa: E402

UNSURE = dict(GOOD, full_name={"value": "דנה כהן", "confidence": 0.5, "legible": True})


class GatedStub(StubClient):
    """The zoomed double check waits for a gate, so the test can look at the form in between."""

    def __init__(self):
        super().__init__(response=UNSURE)
        self.gate = None

    async def call_tool(self, image_b64, media_type, prompt, tool, system=None):
        if "Look again" in prompt:
            await self.gate.wait()
            return {"full_name": {"value": "דנה כהן", "confidence": 0.99, "legible": True}}
        return await super().call_tool(image_b64, media_type, prompt, tool, system)


def _form_and_fields():
    with Session(db.get_engine()) as s:
        form = s.exec(select(Form)).first()
        if form is None:
            return None, {}
        s.expunge(form)
        return form, {f.name: (f.level, f.value, f.manually_corrected)
                      for f in s.exec(select(Field).where(Field.form_id == form.id)).all()}


def test_form_is_reviewable_before_double_check_and_user_edits_survive(tmp_env):
    batch_id = _make_batch(tmp_env, n_files=1)
    stub = GatedStub()
    ctx = _ctx(tmp_env, stub, double_check=True)

    async def main():
        stub.gate = asyncio.Event()
        task = asyncio.create_task(process_batch(batch_id, ctx))
        form = None
        for _ in range(300):
            await asyncio.sleep(0.02)
            form, fields = _form_and_fields()
            if form is not None and form.status == "done":
                break
        assert form.status == "done" and form.refining  # shown while still being checked
        assert fields["full_name"][0] == "review"
        with Session(db.get_engine()) as s:  # the clerk fixes the sender meanwhile
            fld = s.exec(select(Field).where(Field.form_id == form.id, Field.name == "sender")).one()
            fld.value, fld.manually_corrected, fld.version = '"כללית"', True, 1
            s.add(fld)
            s.commit()
        stub.gate.set()
        await task

    asyncio.run(main())
    form, fields = _form_and_fields()
    assert not form.refining
    assert fields["full_name"][0] == "ok"  # confirmed by the zoomed read
    assert fields["sender"][1] == '"כללית"' and fields["sender"][2]  # the person's fix was kept


def test_without_early_save_the_form_appears_only_at_the_end(tmp_env):
    batch_id = _make_batch(tmp_env, n_files=1)
    ctx = _ctx(tmp_env, StubClient())
    ctx.pipeline_cfg = dict(ctx.pipeline_cfg, early_save={"enabled": False})
    asyncio.run(process_batch(batch_id, ctx))
    form, fields = _form_and_fields()
    assert form.status == "done" and not form.refining and fields


def test_batch_poll_never_loads_blobs(tmp_env):
    batch_id = _make_batch(tmp_env, n_files=1)
    asyncio.run(process_batch(batch_id, _ctx(tmp_env, StubClient())))
    statements = []
    engine = db.get_engine()

    def capture(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        with Session(engine) as s:
            detail = batch_detail(s, s.get(Batch, batch_id))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert detail["forms"] and "refining" in detail["forms"][0]
    joined = " ".join(statements)
    assert "image_data" not in joined and "sourcefile.content" not in joined


def test_events_wake_listeners():
    async def main():
        seen = events.version(42)
        waiter = asyncio.create_task(events.wait_change(42, seen, timeout=2))
        await asyncio.sleep(0.01)
        events.bump(42)
        return seen, await asyncio.wait_for(waiter, 1)

    before, after = asyncio.run(main())
    assert after == before + 1
