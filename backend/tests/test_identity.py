"""Identity rules: confident reads skip the clerk (>= 65%), a known ID fixes an unsure name, a clashing name is an error."""
import asyncio

from sqlmodel import Session, select

from app import db, identity
from app.fields import LEVEL_OK, LEVEL_REVIEW
from app.models import Form
from pipeline.base import FieldResult, FormDoc
from pipeline.runner import process_batch
from pipeline.stages.confidence import base_level
from tests.test_patients import VALID_ID, _commitment
from tests.test_pipeline_failure import GOOD, StubClient, _ctx, _fields, _make_batch

CFG = {"confidence": {"threshold": 0.65}, "identity": {"id_min_confidence": 0.70, "name_match": 75}}


def _doc(name, name_conf, id_value=VALID_ID, id_conf=0.9, name_legible=True):
    fields = {
        "full_name": FieldResult(value=name, confidence=name_conf, legible=name_legible, level=LEVEL_REVIEW),
        "id_number": FieldResult(value=id_value, confidence=id_conf, level=LEVEL_OK),
    }
    return FormDoc(batch_id=1, source_file_id=1, fields=fields)


def _reconcile(doc):
    with Session(db.get_engine()) as s:
        identity.reconcile(s, doc, None, CFG)
    return doc.fields["full_name"], doc.fields["id_number"]


def test_confidence_from_65_percent_is_ok_below_is_review():
    assert base_level(FieldResult(value="x", confidence=0.66), 0.65) == LEVEL_OK
    assert base_level(FieldResult(value="x", confidence=0.64), 0.65) == LEVEL_REVIEW


def test_unsure_name_takes_the_name_filed_under_the_id(tmp_env):
    _commitment(VALID_ID, name="דנה כהן", numbers=("999",))
    for garbled, conf in (("דנח כחז", 0.3), (None, 0.0), ("דנה כהן-לוי מחובר", 0.5)):
        name, ident = _reconcile(_doc(garbled, conf))
        assert name.value == "דנה כהן" and name.level == LEVEL_OK
        assert {"kind": "info", "code": "name_from_patient_file"} in name.reasons
        assert not any(r["kind"] == "soft" for r in name.reasons)
        assert ident.level == LEVEL_OK


def test_unsure_name_is_kept_when_the_id_is_not_trusted_or_unknown(tmp_env):
    _commitment(VALID_ID, name="דנה כהן", numbers=("999",))
    name, _ = _reconcile(_doc("דנח", 0.3, id_conf=0.6))  # ID under 70%
    assert name.value == "דנח"
    name, _ = _reconcile(_doc("דנח", 0.3, id_value="123456789"))  # bad check digit
    assert name.value == "דנח"
    name, _ = _reconcile(_doc("דנח", 0.3, id_value="000000018"))  # nobody filed under it
    assert name.value == "דנח"


def test_clear_name_that_differs_from_the_filed_one_is_an_error(tmp_env):
    _commitment(VALID_ID, name="דנה כהן", numbers=("999",))
    name, ident = _reconcile(_doc("יוסי לוי", 0.9))
    assert name.value == "יוסי לוי"  # never overwritten: a person decides which is right
    for fr in (name, ident):
        assert fr.level == LEVEL_REVIEW
        assert {"kind": "validation", "code": "id_name_conflict"} in fr.reasons


def test_same_name_spelled_differently_or_in_another_script_is_no_conflict(tmp_env):
    _commitment(VALID_ID, name="דנה כהן", numbers=("999",))
    for other in ("דנה כוהן", "כהן דנה", "Dana Cohen"):
        name, ident = _reconcile(_doc(other, 0.9))
        assert not any(r["code"] == "id_name_conflict" for r in name.reasons + ident.reasons), other
        assert name.value == other


def test_handwritten_clear_name_is_still_compared(tmp_env):
    """A handwritten name is always 'review' by level, yet read at 90% it is a clear read: a clash is an error."""
    _commitment(VALID_ID, name="דנה כהן", numbers=("999",))
    doc = _doc("יוסי לוי", 0.9)
    doc.fields["full_name"].handwritten = True
    name, _ = _reconcile(doc)
    assert any(r["code"] == "id_name_conflict" for r in name.reasons)


def test_pipeline_unsure_name_with_known_id_goes_straight_to_approval(tmp_env):
    _commitment(VALID_ID, name="דנה כהן", numbers=("999",))
    resp = dict(GOOD, full_name={"value": "דנח כחז", "confidence": 0.3, "legible": True})
    batch_id = _make_batch(tmp_env, n_files=1)
    asyncio.run(process_batch(batch_id, _ctx(tmp_env, StubClient(response=resp))))
    with Session(db.get_engine()) as s:
        form = s.exec(select(Form).where(Form.batch_id == batch_id)).one()
    assert _fields(form.id)["full_name"].value == '"דנה כהן"'
    assert form.workflow == "pending_approval"


def test_pipeline_name_clash_stays_with_the_clerk(tmp_env):
    _commitment(VALID_ID, name="דנה כהן", numbers=("999",))
    resp = dict(GOOD, full_name={"value": "יוסי לוי", "confidence": 0.95, "legible": True})
    batch_id = _make_batch(tmp_env, n_files=1)
    asyncio.run(process_batch(batch_id, _ctx(tmp_env, StubClient(response=resp))))
    with Session(db.get_engine()) as s:
        form = s.exec(select(Form).where(Form.batch_id == batch_id)).one()
    f = _fields(form.id)
    assert form.workflow == "needs_fix"
    assert "id_name_conflict" in f["full_name"].reasons and "id_name_conflict" in f["id_number"].reasons
