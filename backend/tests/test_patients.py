"""Patient file (roadmap 2ד): linking by ID, suggested vs automatic links, referrals read lightly, search, audit."""
import asyncio
import json

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import db
from app.main import app
from app.models import AuditLog, Batch, Field, Form, SourceFile
from app.patients import link_patient, patient_key
from pipeline.runner import process_batch
from pipeline.stages.document import parse_document
from tests.test_pipeline_failure import GOOD, StubClient, _ctx, _make_batch

VALID_ID = "123456782"


def _commitment(id_value, level="ok", name="דנה כהן", numbers=("555",), date="2026-03-05"):
    with Session(db.get_engine()) as s:
        b = Batch(status="done")
        s.add(b)
        s.commit()
        sf = SourceFile(batch_id=b.id, filename="a.png", path="a.png", status="done")
        s.add(sf)
        s.commit()
        fm = Form(batch_id=b.id, source_file_id=sf.id, status="done", workflow="needs_fix")
        s.add(fm)
        s.commit()
        for n, v, lv in (("id_number", id_value, level), ("full_name", name, "ok"),
                         ("commitment_numbers", list(numbers), "ok"), ("receipt_date", date, "ok")):
            s.add(Field(form_id=fm.id, name=n, value=json.dumps(v, ensure_ascii=False), level=lv))
        s.commit()
        link_patient(s, fm)
        s.commit()
        return fm.id


def _form(form_id):
    with Session(db.get_engine()) as s:
        return s.get(Form, form_id)


def test_patient_key_restores_leading_zeros():
    assert patient_key("12345678") == "012345678"
    assert patient_key("ת.ז. 0-1234-5678") == "012345678"
    assert patient_key("1234567890") is None and patient_key(None) is None


def test_valid_confident_id_links_automatically_else_suggested(tmp_env):
    auto = _commitment(VALID_ID)
    unsure = _commitment(VALID_ID, level="review")
    bad = _commitment("123456789")
    assert _form(auto).patient_link == "auto"
    assert _form(unsure).patient_link == "suggested"
    assert _form(bad).patient_link == "suggested"


def test_patient_file_groups_forms_and_view_is_audited(tmp_env):
    a = _commitment(VALID_ID, date="2026-03-01")
    b = _commitment(VALID_ID, date="2026-04-01", name="Dana Cohen")
    s_id = _commitment(VALID_ID, level="review")
    _commitment("000000018")
    with TestClient(app) as client:
        r = client.get(f"/api/patients/{VALID_ID}")
        assert r.status_code == 200
        body = r.json()
    assert [c["id"] for c in body["commitments"]] == [b, a]  # newest first
    assert [c["id"] for c in body["suggested"]] == [s_id]
    assert set(body["names"]) == {"דנה כהן", "Dana Cohen"}
    with Session(db.get_engine()) as s:
        rows = s.exec(select(AuditLog).where(AuditLog.action == "patient_viewed")).all()
    assert len(rows) == 1 and json.loads(rows[0].after) == {"patient_id": VALID_ID}


def test_search_by_id_name_and_commitment_number(tmp_env):
    _commitment(VALID_ID, name="דנה כהן", numbers=("777",))
    _commitment("000000018", name="Israel Israeli", numbers=("888",))
    with TestClient(app) as client:
        def ids(q):
            return [p["patient_id"] for p in client.get("/api/patients", params={"q": q}).json()]
        assert ids("123456782") == [VALID_ID]
        assert ids("כהן") == [VALID_ID]
        assert ids("israeli") == ["000000018"]
        assert ids("888") == ["000000018"]
        assert len(ids("")) == 2


def test_manual_decision_is_never_overwritten(tmp_env):
    fid = _commitment(VALID_ID, level="review")
    with TestClient(app) as client:
        assert client.post(f"/api/forms/{fid}/patient", json={"action": "confirm"}).json()["patient_link"] == "manual"
        other = _commitment(VALID_ID)
        client.post(f"/api/forms/{other}/patient", json={"action": "reject"})
    with Session(db.get_engine()) as s:
        for f in (fid, other):
            fm = s.get(Form, f)
            link_patient(s, fm)
        s.commit()
    assert _form(fid).patient_link == "manual"
    assert _form(other).patient_link == "rejected"


def test_correcting_the_id_moves_the_form(tmp_env):
    fid = _commitment("123456789", level="review")
    with Session(db.get_engine()) as s:
        fld_id = s.exec(select(Field.id).where(Field.form_id == fid, Field.name == "id_number")).one()
    with TestClient(app) as client:
        client.patch(f"/api/fields/{fld_id}", json={"value": VALID_ID})
    assert _form(fid).patient_id == VALID_ID and _form(fid).patient_link == "auto"


def test_parse_document_files_only_confident_valid_ids():
    sure = parse_document({"id_number": VALID_ID, "id_confidence": 0.95, "doc_kind": "referral",
                           "full_name": "דנה כהן", "test_type": "PCR"})
    assert sure["id_confident"] and sure["doc_kind"] == "referral" and sure["test_type"] == "PCR"
    assert not parse_document({"id_number": VALID_ID, "id_confidence": 0.4, "doc_kind": "referral"})["id_confident"]
    assert parse_document({"id_number": None, "doc_kind": "weird"})["doc_kind"] == "other"


class ReferralStub(StubClient):
    """Classify says 'other_medical'; the light document read returns who it is about."""

    async def call_tool(self, image_b64, media_type, prompt, tool, system=None):
        if tool["name"] == "record_orientation":
            return {"clockwise_degrees": 0, "doc_type": "other_medical"}
        if tool["name"] == "record_document":
            return {"id_number": VALID_ID, "id_confidence": 0.97, "doc_kind": "referral",
                    "full_name": "דנה כהן", "doc_date": "01/03/2026", "test_type": "PCR"}
        return GOOD


def test_referral_page_lands_in_the_patient_file(tmp_env):
    batch_id = _make_batch(tmp_env, n_files=1)
    ctx = _ctx(tmp_env, ReferralStub())
    asyncio.run(process_batch(batch_id, ctx))
    with Session(db.get_engine()) as s:
        fm = s.exec(select(Form)).one()
        assert fm.doc_type == "other_medical" and fm.patient_id == VALID_ID and fm.patient_link == "auto"
        assert json.loads(fm.doc_meta)["doc_date"] == "2026-03-01"
    with TestClient(app) as client:
        docs = client.get(f"/api/patients/{VALID_ID}").json()["documents"]
    assert docs[0]["doc_meta"]["doc_kind"] == "referral"
