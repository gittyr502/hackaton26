"""Edge cases end to end with a stubbed Claude client: bad uploads fail alone with a code, pages that are
not commitments are kept but not read, multi-page and multi-form pages, timeouts, API down, restart,
per-file upload, concurrent edits and duplicates."""
import asyncio
import base64
import io
import json
import time

import fitz
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlmodel import Session, select

from app import db
from app.models import Batch, Field, Form, SourceFile
from pipeline import control
from pipeline.claude_client import ApiUnavailable
from pipeline.runner import build_context, process_batch, process_uploaded_file, retry_form
from tests.test_pipeline_failure import GOOD

WHITE, RED, BLUE, GREEN = (255, 255, 255), (220, 30, 30), (30, 30, 220), (30, 160, 30)


def _color_of(image_b64, tiles=False):
    with Image.open(io.BytesIO(base64.b64decode(image_b64))) as im:
        im = im.convert("RGB")
        if tiles:  # the orientation check sends a 2x2 sheet of the page: look inside tile A only
            im = im.crop((44, 44, 84, 84))
        r, g, b = im.resize((1, 1)).getpixel((0, 0))
    return min((WHITE, RED, BLUE, GREEN), key=lambda c: sum(abs(x - y) for x, y in zip(c, (r, g, b))))


class PageStub:
    """Answers by the page's colour, so concurrent pages get the right answer whatever the call order."""

    def __init__(self, classify=None, extract=None, fail=None):
        self.classify = classify or {}
        self.extract = extract or {}
        self.fail = fail
        self.calls = {"record_orientation": 0, "record_form": 0}

    async def call_tool(self, image_b64, media_type, prompt, tool, system=None):
        self.calls[tool["name"]] = self.calls.get(tool["name"], 0) + 1
        if self.fail is not None:
            raise self.fail
        color = _color_of(image_b64, tiles=tool["name"] == "record_orientation")
        if tool["name"] == "record_orientation":
            return dict({"clockwise_degrees": 0}, **self.classify.get(color, {}))
        return self.extract.get(color, GOOD)


def _ctx(settings, client, **cfg):
    ctx = build_context(settings, client=client)
    ctx.senders_cfg = {"match_threshold": 85, "senders": [{"name": "מכבי", "aliases": []}]}
    ctx.pipeline_cfg = dict(ctx.pipeline_cfg, double_check={"enabled": False}, **cfg)
    return ctx


def _batch_with(settings, files):
    """files: {name: bytes}. Returns the batch id."""
    up = settings.batches_dir / "1" / "uploads"
    up.mkdir(parents=True, exist_ok=True)
    with Session(db.get_engine()) as s:
        b = Batch()
        s.add(b)
        s.commit()
        s.refresh(b)
        for name, data in files.items():
            p = up / name
            p.write_bytes(data)
            s.add(SourceFile(batch_id=b.id, filename=name, path=str(p)))
        s.commit()
        return b.id


def _png(color=WHITE, size=(300, 400)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _pdf(colors, **save_kw):
    doc = fitz.open()
    for c in colors:
        page = doc.new_page(width=300, height=400)
        fill = tuple(x / 255 for x in c)
        page.draw_rect(page.rect, color=fill, fill=fill)
    out = doc.tobytes(**save_kw)
    doc.close()
    return out


def _run(settings, client, files, **cfg):
    batch_id = _batch_with(settings, files)
    asyncio.run(process_batch(batch_id, _ctx(settings, client, **cfg)))
    return batch_id


def _files():
    with Session(db.get_engine()) as s:
        return {f.filename: f for f in s.exec(select(SourceFile)).all()}


def _forms():
    with Session(db.get_engine()) as s:
        return s.exec(select(Form).order_by(Form.page_index, Form.region_index)).all()


def _fields(form_id):
    with Session(db.get_engine()) as s:
        return {f.name: f for f in s.exec(select(Field).where(Field.form_id == form_id)).all()}


# ---------- bad uploads fail alone, with a code ----------

def test_empty_corrupt_and_password_files_fail_alone_with_codes(tmp_env):
    batch_id = _run(tmp_env, PageStub(), {
        "empty.pdf": b"",
        "garbage.pdf": b"%PDF-1.4\nthis is not a pdf at all",
        "locked.pdf": _pdf([RED], encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="u", owner_pw="o"),
        "notes.png": b"hello, I am text",
        "good.png": _png(RED),
    })
    files = _files()
    assert files["empty.pdf"].error_code == "empty_file"
    assert files["garbage.pdf"].error_code == "corrupt_file"
    assert files["locked.pdf"].error_code == "password_protected"
    assert files["notes.png"].error_code == "unsupported_type"
    assert files["good.png"].status == "done"
    assert all(files[n].status == "failed" for n in ("empty.pdf", "garbage.pdf", "locked.pdf", "notes.png"))
    with Session(db.get_engine()) as s:
        assert s.get(Batch, batch_id).status == "done"


def test_truncated_pdf_keeps_what_can_be_read(tmp_env):
    data = _pdf([RED, BLUE, GREEN])
    _run(tmp_env, PageStub(), {"cut.pdf": data[: len(data) // 2]})
    f = _files()["cut.pdf"]
    if f.status == "failed":
        assert f.error_code == "corrupt_file"
    else:
        assert set(json.loads(f.warnings)) & {"file_repaired", "pages_missing"}


def test_truncated_image_is_read_and_flagged(tmp_env):
    buf = io.BytesIO()
    Image.new("RGB", (300, 400), RED).save(buf, "JPEG", quality=95)
    data = buf.getvalue()
    _run(tmp_env, PageStub(), {"cut.jpg": data[: int(len(data) * 0.7)]})
    f = _files()["cut.jpg"]
    if f.status == "done":
        form = _forms()[0]
        assert "truncated_image" in json.loads(form.reasons)
        assert form.workflow == "needs_fix"
    else:
        assert f.error_code == "corrupt_file"


# ---------- what is on the page ----------

def test_blank_and_other_documents_are_kept_but_not_read(tmp_env):
    stub = PageStub(classify={WHITE: {"doc_type": "blank"}, BLUE: {"doc_type": "other_medical"}})
    _run(tmp_env, stub, {"scan.pdf": _pdf([RED, WHITE, BLUE])})
    forms = _forms()
    assert [f.doc_type for f in forms] == ["commitment", "blank", "other_medical"]
    assert all(f.status == "done" for f in forms)
    assert forms[0].workflow is not None and forms[1].workflow is None and forms[2].workflow is None
    assert _fields(forms[1].id) == {} and _fields(forms[2].id) == {}
    assert stub.calls["record_form"] == 1  # only the commitment was read


def test_blank_answer_on_a_page_with_ink_is_read_anyway(tmp_env):
    _run(tmp_env, PageStub(classify={RED: {"doc_type": "blank"}}), {"a.png": _png(RED)})
    form = _forms()[0]
    assert form.doc_type == "commitment" and "blank_uncertain" in json.loads(form.reasons)
    assert _fields(form.id)


def test_user_override_reads_a_page_classified_as_other(tmp_env):
    stub = PageStub(classify={BLUE: {"doc_type": "unrelated"}})
    _run(tmp_env, stub, {"a.png": _png(BLUE)})
    form = _forms()[0]
    assert form.doc_type == "unrelated" and not _fields(form.id)
    asyncio.run(retry_form(form.id, _ctx(tmp_env, stub), forced_type="commitment"))
    form = _forms()[0]
    assert form.doc_type == "commitment" and form.status == "done"
    assert _fields(form.id)["full_name"].value is not None


def test_poor_photo_and_cut_off_form_go_to_review(tmp_env):
    _run(tmp_env, PageStub(classify={RED: {"quality": "poor", "cut_off": True}}), {"a.png": _png(RED)})
    form = _forms()[0]
    assert {"poor_quality", "partial_page"} <= set(json.loads(form.reasons))
    assert form.workflow == "needs_fix"  # every field may look fine; the form still needs a human


def test_empty_form_is_flagged(tmp_env):
    empty = {n: {"value": None, "confidence": 0.9, "legible": True} for n in GOOD}
    _run(tmp_env, PageStub(extract={RED: empty}), {"a.png": _png(RED)})
    assert "empty_form" in json.loads(_forms()[0].reasons)


# ---------- several commitments on one page ----------

def test_two_commitments_on_one_page_become_two_forms(tmp_env):
    stub = PageStub(classify={RED: {"commitments_count": 2,
                                    "regions": [[0, 0, 1, 0.5], [0, 0.5, 1, 1]]}})
    _run(tmp_env, stub, {"stickers.png": _png(RED)})
    forms = _forms()
    assert len(forms) == 2
    assert sorted(f.region_index for f in forms) == [0, 1]
    assert all("multiple_commitments" in json.loads(f.reasons) for f in forms)
    assert all(f.status == "done" and f.workflow == "needs_fix" for f in forms)
    with Image.open(io.BytesIO(forms[1].image_data)) as im:
        assert im.size[1] < 400  # its own crop, not the whole page
    assert _files()["stickers.png"].progress == 1.0


def test_several_commitments_without_boxes_only_flag_the_page(tmp_env):
    _run(tmp_env, PageStub(classify={RED: {"commitments_count": 3}}), {"a.png": _png(RED)})
    forms = _forms()
    assert len(forms) == 1 and "multiple_commitments" in json.loads(forms[0].reasons)


# ---------- one commitment over several pages ----------

def _two_page_commitment(tmp_env, page2):
    stub = PageStub(classify={BLUE: {"doc_type": "continuation"}},
                    extract={RED: dict(GOOD, central_numbers={"value": ["A1"], "confidence": 0.95, "legible": True},
                                       sender={"value": None, "confidence": 0.9, "legible": True}),
                             BLUE: page2})
    _run(tmp_env, stub, {"two.pdf": _pdf([RED, BLUE])})
    forms = _forms()
    assert len(forms) == 2
    return forms


def test_continuation_page_is_merged_into_its_commitment(tmp_env):
    page2 = {n: {"value": None, "confidence": 0.9, "legible": True} for n in GOOD}
    page2["central_numbers"] = {"value": ["A2"], "confidence": 0.95, "legible": True}
    page2["sender"] = {"value": "מכבי", "confidence": 0.95, "legible": True}
    parent, child = _two_page_commitment(tmp_env, page2)
    assert child.parent_form_id == parent.id and child.workflow is None
    assert "merged_pages" in json.loads(parent.reasons)
    f = _fields(parent.id)
    assert json.loads(f["central_numbers"].value) == ["A1", "A2"]  # numbers from both pages
    assert json.loads(f["sender"].value) == "מכבי"  # filled from page 2


def test_pages_that_disagree_go_to_review_and_split_restores(tmp_env):
    page2 = dict(GOOD, full_name={"value": "יוסי לוי", "confidence": 0.99, "legible": True})
    parent, child = _two_page_commitment(tmp_env, page2)
    f = _fields(parent.id)["full_name"]
    assert f.level == "review" and "pages_disagree" in f.reasons
    assert json.loads(f.value) == "דנה כהן"  # the first page's reading is kept

    with TestClient(__import__("app.main", fromlist=["app"]).app) as client:
        r = client.post(f"/api/forms/{parent.id}/split")
        assert r.status_code == 200, r.text
    with Session(db.get_engine()) as s:
        parent, child = s.get(Form, parent.id), s.get(Form, child.id)
        assert child.parent_form_id is None and child.workflow is not None
        assert "merged_pages" not in json.loads(parent.reasons)
    assert "pages_disagree" not in _fields(parent.id)["full_name"].reasons

    with TestClient(__import__("app.main", fromlist=["app"]).app) as client:
        assert client.post(f"/api/forms/{child.id}/merge-previous").status_code == 200
    with Session(db.get_engine()) as s:
        assert s.get(Form, child.id).parent_form_id == parent.id


def test_continuation_without_a_page_before_is_its_own_form(tmp_env):
    _run(tmp_env, PageStub(classify={BLUE: {"doc_type": "continuation"}}), {"a.png": _png(BLUE)})
    form = _forms()[0]
    assert form.parent_form_id is None and form.doc_type == "commitment" and form.workflow


# ---------- slow scanning, API down, restart ----------

def test_a_stuck_page_times_out_alone(tmp_env):
    class Slow(PageStub):
        async def call_tool(self, image_b64, media_type, prompt, tool, system=None):
            if tool["name"] == "record_form" and _color_of(image_b64) == BLUE:
                await asyncio.sleep(5)
            return await super().call_tool(image_b64, media_type, prompt, tool, system)

    extract_cfg = dict(build_context(tmp_env, client=object()).pipeline_cfg.get("extract", {}),
                       stage_timeout_seconds=0.5)
    batch_id = _run(tmp_env, Slow(), {"a.png": _png(RED), "b.png": _png(BLUE)}, extract=extract_cfg)
    by_color = {f.source_file_id: f for f in _forms()}
    files = _files()
    assert by_color[files["a.png"].id].status == "done"
    stuck = by_color[files["b.png"].id]
    assert stuck.status == "failed" and stuck.error_code == "timeout"
    with Session(db.get_engine()) as s:
        assert s.get(Batch, batch_id).status == "done"


def test_api_unavailable_pauses_the_batch_once(tmp_env):
    async def scenario():
        batch_id = _batch_with(tmp_env, {"a.png": _png(RED)})
        task = asyncio.create_task(process_batch(batch_id, _ctx(tmp_env, PageStub(fail=ApiUnavailable("x")))))
        for _ in range(100):
            await asyncio.sleep(0.02)
            if control.is_paused(batch_id):
                break
        assert control.is_paused(batch_id)
        with Session(db.get_engine()) as s:
            assert s.get(Batch, batch_id).notice == "api_unavailable"
            assert s.exec(select(Form)).first().error_code == "api_unavailable"
        control.resume(batch_id)
        await task

    asyncio.run(scenario())


def test_restart_marks_interrupted_work_with_a_code(tmp_env):
    from app.main import recover_interrupted

    batch_id = _batch_with(tmp_env, {"a.png": _png(RED)})
    with Session(db.get_engine()) as s:
        sf = s.exec(select(SourceFile)).first()
        sf.status = "processing"
        s.add(sf)
        s.add(Form(batch_id=batch_id, source_file_id=sf.id, status="processing"))
        s.commit()
    recover_interrupted()
    with Session(db.get_engine()) as s:
        assert s.exec(select(Form)).first().error_code == "interrupted"
        assert s.exec(select(SourceFile)).first().error_code == "interrupted"
        b = s.get(Batch, batch_id)
        assert b.status == "done" and b.finished_at is not None


def test_cancel_keeps_finished_forms(tmp_env):
    class Gate(PageStub):
        def __init__(self):
            super().__init__()
            self.release = None

        async def call_tool(self, image_b64, media_type, prompt, tool, system=None):
            if tool["name"] == "record_form" and _color_of(image_b64) == BLUE:
                await self.release.wait()
            return await super().call_tool(image_b64, media_type, prompt, tool, system)

    async def scenario():
        stub = Gate()
        stub.release = asyncio.Event()
        batch_id = _batch_with(tmp_env, {"a.png": _png(RED), "b.png": _png(BLUE)})
        task = asyncio.create_task(process_batch(batch_id, _ctx(tmp_env, stub)))
        for _ in range(200):
            await asyncio.sleep(0.02)
            if any(f.status == "done" for f in _forms()):
                break
        control.cancel(batch_id)
        stub.release.set()
        await task

    asyncio.run(scenario())
    statuses = sorted(f.status for f in _forms())
    assert "done" in statuses  # the finished form stays reviewable


# ---------- per-file upload ----------

def test_per_file_upload_reads_each_file_and_finishes_the_batch(tmp_env, monkeypatch):
    from app.api import batches
    from app.main import app

    stub = PageStub()

    async def run_with_stub(sf_id, batch_id):
        await process_uploaded_file(sf_id, batch_id, _ctx(tmp_env, stub))

    monkeypatch.setattr(batches, "process_uploaded_file", run_with_stub)
    with TestClient(app) as client:
        batch_id = client.post("/api/batches/open", json={"expected_files": 3}).json()["id"]
        r1 = client.post(f"/api/batches/{batch_id}/files", files={"file": ("a.png", _png(RED), "image/png")})
        r2 = client.post(f"/api/batches/{batch_id}/files", files={"file": ("empty.pdf", b"", "application/pdf")})
        assert r1.json()["status"] == "pending" and r2.json()["error_code"] == "empty_file"
        assert client.get(f"/api/batches/{batch_id}").json()["status"] == "processing"  # 1 file still missing
        r3 = client.post(f"/api/batches/{batch_id}/files", files={"file": ("a.png", _png(RED), "image/png")})
        assert r3.status_code == 200
        assert client.post(f"/api/batches/{batch_id}/files",
                           files={"file": ("x.png", _png(RED), "image/png")}).status_code == 409
        detail = None
        for _ in range(200):
            detail = client.get(f"/api/batches/{batch_id}").json()
            if detail["status"] == "done":
                break
            time.sleep(0.05)
        assert detail["status"] == "done"
        assert sorted(f["status"] for f in detail["files"]) == ["done", "done", "failed"]


def test_closing_an_upload_finishes_with_what_arrived(tmp_env):
    from app.main import app

    with TestClient(app) as client:
        batch_id = client.post("/api/batches/open", json={"expected_files": 2}).json()["id"]
        client.post(f"/api/batches/{batch_id}/files", files={"file": ("e.pdf", b"", "application/pdf")})
        assert client.post(f"/api/batches/{batch_id}/close").json()["status"] == "done"


def test_duplicate_file_is_flagged_not_blocked(tmp_env):
    from app.main import app

    with TestClient(app) as client:
        first = client.post("/api/batches/open", json={"expected_files": 1}).json()["id"]
        client.post(f"/api/batches/{first}/files", files={"file": ("e.pdf", b"%PDF-x", "application/pdf")})
        second = client.post("/api/batches/open", json={"expected_files": 1}).json()["id"]
        r = client.post(f"/api/batches/{second}/files", files={"file": ("e.pdf", b"%PDF-x", "application/pdf")})
        assert r.status_code == 200 and r.json()["duplicate_of_batch"] == first


def test_duplicate_commitment_number_is_flagged(tmp_env):
    _run(tmp_env, PageStub(), {"a.png": _png(RED), "b.png": _png(BLUE)})
    reasons = [json.loads(f.reasons) for f in _forms()]
    assert sum("possible_duplicate" in r for r in reasons) >= 1


# ---------- concurrent edits ----------

def test_stale_edit_is_refused_with_who_changed_it(tmp_env):
    from app.main import app

    _run(tmp_env, PageStub(), {"a.png": _png(RED)})
    fld = _fields(_forms()[0].id)["full_name"]
    with TestClient(app) as client:
        r = client.patch(f"/api/fields/{fld.id}", json={"value": "א ב", "version": fld.version})
        assert r.status_code == 200 and r.json()["version"] == fld.version + 1
        stale = client.patch(f"/api/fields/{fld.id}", json={"value": "ג ד", "version": fld.version})
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "conflict" and stale.json()["detail"]["by"]
        # without a version the old behaviour stays: last write wins
        assert client.patch(f"/api/fields/{fld.id}", json={"value": "ה ו"}).status_code == 200


@pytest.mark.parametrize("doc_type", ["unrelated", "blank"])
def test_user_can_mark_a_page_as_not_a_commitment(tmp_env, doc_type):
    from app.main import app

    _run(tmp_env, PageStub(), {"a.png": _png(RED)})
    form = _forms()[0]
    with TestClient(app) as client:
        assert client.post(f"/api/forms/{form.id}/doc-type", json={"doc_type": doc_type}).status_code == 200
    form = _forms()[0]
    assert form.doc_type == doc_type and form.workflow is None and not _fields(form.id)
