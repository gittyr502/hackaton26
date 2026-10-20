"""Corrections teach the pipeline: recorded on edit, learned once approved, applied on later forms."""
import asyncio
import json

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import db
from app.main import app
from app.models import Batch, Correction, Field, Form, SourceFile
from pipeline.learning import char_confusions, load_lessons
from pipeline.runner import process_batch
from tests.test_pipeline_failure import GOOD, StubClient, _ctx, _fields, _make_batch

SENDERS = {"match_threshold": 85, "senders": [{"name": "מכבי", "aliases": []}, {"name": "כללית", "aliases": []}]}


def _seed(model_value, raw, corrected, name="sender", level="review", workflow="approved"):
    """An approved form with one human correction, as it is after the approver signed off."""
    with Session(db.get_engine()) as s:
        b = Batch(status="done")
        s.add(b)
        s.commit()
        sf = SourceFile(batch_id=b.id, filename="a.png", path="a.png", status="done")
        s.add(sf)
        s.commit()
        fm = Form(batch_id=b.id, source_file_id=sf.id, status="done", workflow=workflow)
        s.add(fm)
        s.commit()
        dump = lambda v: None if v is None else json.dumps(v, ensure_ascii=False)  # noqa: E731
        s.add(Correction(form_id=fm.id, field_name=name, model_value=dump(model_value), raw_value=dump(raw),
                         corrected_value=dump(corrected), model_level=level))
        s.commit()
        return fm.id


def _lessons(**cfg):
    with Session(db.get_engine()) as s:
        return load_lessons(s, cfg, SENDERS)


def test_char_confusions():
    assert char_confusions("123456781", "123456782") == [("1", "2")]
    assert char_confusions("דנה", "דנה") == []
    assert char_confusions("abcdef", "xyz") == []  # a different word is not a misread character


def test_edit_records_a_correction_and_reset_forgets_it(tmp_env):
    _, form_id, ids = _seed_form_with_fields()
    client = TestClient(app)
    assert client.patch(f"/api/fields/{ids[1]}", json={"value": "כללית"}).status_code == 200
    with Session(db.get_engine()) as s:
        c = s.exec(select(Correction)).one()
        assert (json.loads(c.model_value), json.loads(c.corrected_value)) == ("מכבי", "כללית")
        assert c.field_name == "sender" and c.form_id == form_id

    client.patch(f"/api/fields/{ids[1]}", json={"value": "מאוחדת"})  # edited again: same row, new answer
    with Session(db.get_engine()) as s:
        c = s.exec(select(Correction)).one()
        assert json.loads(c.model_value) == "מכבי" and json.loads(c.corrected_value) == "מאוחדת"

    client.post(f"/api/fields/{ids[1]}/reset")
    with Session(db.get_engine()) as s:
        assert s.exec(select(Correction)).all() == []


def test_editing_back_to_the_models_value_is_not_a_correction(tmp_env):
    _, _, ids = _seed_form_with_fields()
    client = TestClient(app)
    client.patch(f"/api/fields/{ids[1]}", json={"value": "כללית"})
    client.patch(f"/api/fields/{ids[1]}", json={"value": "מכבי"})
    with Session(db.get_engine()) as s:
        assert s.exec(select(Correction)).all() == []


def _seed_form_with_fields():
    from tests.test_workflow import _seed_form
    return _seed_form(workflow="needs_fix", levels=("ok", "ok"))


def test_only_approved_corrections_teach(tmp_env):
    for _ in range(2):
        _seed("כלליית", "כלליית", "כללית", workflow="pending_approval")
    assert _lessons().sender_aliases == {}


def test_sender_alias_needs_two_forms_and_no_disagreement(tmp_env):
    _seed("כלליית", "כלליית", "כללית")
    assert _lessons().sender_aliases == {}  # one form is an anecdote
    _seed("כלליית", "כלליית", "כללית")
    assert _lessons().sender_aliases == {"כלליית": "כללית"}
    _seed("כלליית", "כלליית", "מכבי")  # reviewers disagree: learn nothing
    assert _lessons().sender_aliases == {}


def test_alias_to_unknown_sender_is_ignored(tmp_env):
    for _ in range(2):
        _seed("xx", "xx", "לא ברשימה")
    assert _lessons().sender_aliases == {}


def test_learned_alias_is_applied_by_the_pipeline(tmp_env):
    for _ in range(2):
        _seed("מקבי", "מקבי", "כללית")
    resp = dict(GOOD, sender={"value": "מקבי", "confidence": 0.99, "legible": True})
    batch_id = _make_batch(tmp_env, n_files=1)
    ctx = _ctx(tmp_env, StubClient(response=resp))
    ctx.senders_cfg = SENDERS
    ctx.lessons = _lessons()
    asyncio.run(process_batch(batch_id, ctx))
    with Session(db.get_engine()) as s:
        form = s.exec(select(Form).where(Form.batch_id == batch_id)).one()
    f = _fields(form.id)["sender"]
    assert json.loads(f.value) == "כללית" and f.level == "ok"
    assert "learned_correction" in f.reasons


def test_prompt_lists_patterns_not_patient_data(tmp_env):
    for _ in range(2):
        _seed("123456781", "123456781", "123456782", name="id_number", level="ok")
    for _ in range(2):
        _seed(None, None, "שם כלשהו", name="full_name")
    text = _lessons().prompt_for(["id_number", "full_name"])
    assert "'1'" in text and "'2'" in text and "returned null 2 times" in text
    assert "123456782" not in text and "שם כלשהו" not in text


def test_confident_mistakes_hold_a_field_for_review(tmp_env):
    for _ in range(20):
        _seed("A1", "A1", "A2", name="central_numbers", level="ok")
    lessons = _lessons()
    assert "central_numbers" in lessons.risky
    batch_id = _make_batch(tmp_env, n_files=1)
    ctx = _ctx(tmp_env, StubClient())
    ctx.lessons = lessons
    asyncio.run(process_batch(batch_id, ctx))
    with Session(db.get_engine()) as s:
        form = s.exec(select(Form).where(Form.batch_id == batch_id)).one()
    f = _fields(form.id)
    assert f["central_numbers"].level == "review" and "often_corrected" in f["central_numbers"].reasons
    assert f["full_name"].level == "ok"


def test_mistakes_the_model_already_flagged_do_not_hold_fields(tmp_env):
    for _ in range(20):
        _seed("A1", "A1", "A2", name="central_numbers", level="review")
    assert _lessons().risky == {}


def test_learning_can_be_switched_off(tmp_env):
    for _ in range(2):
        _seed("כלליית", "כלליית", "כללית")
    assert _lessons(enabled=False).sender_aliases == {}


def test_retry_keeps_the_lesson(tmp_env):
    _, form_id, ids = _seed_form_with_fields()
    TestClient(app).patch(f"/api/fields/{ids[1]}", json={"value": "כללית"})
    from pipeline.runner import save_fields
    from pipeline.base import FormDoc
    save_fields(form_id, FormDoc(batch_id=1, source_file_id=1, form_id=form_id))
    with Session(db.get_engine()) as s:
        c = s.exec(select(Correction)).one()
        assert c.field_id is None and json.loads(c.corrected_value) == "כללית"


def test_manager_sees_what_was_learned(tmp_env, as_role):
    for _ in range(2):
        _seed("כלליית", "כלליית", "כללית")
    client = TestClient(app)
    body = client.get("/api/learning").json()
    assert body["sender_aliases"] == [{"spelling": "כלליית", "sender": "כללית"}]
    assert body["per_field"]["sender"]["corrections"] == 2
    as_role("intake")
    assert client.get("/api/learning").status_code == 403
