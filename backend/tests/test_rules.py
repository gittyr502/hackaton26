"""Validation rules in plain Hebrew (roadmap 2ד): engine, conversion checks, dry run, pipeline, activation."""
import asyncio
import json

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import db
from app.api.rules import get_rules_client
from app.main import app
from app.models import Field, Form, ValidationRule
from app.rules_nl import parse_rule
from pipeline.runner import process_batch
from tests.conftest import SENDERS_CFG
from tests.test_pipeline_failure import GOOD, StubClient, _ctx, _make_batch
from tests.test_workflow import _seed_form
from validators.rules import describe_he, evaluate, validate_spec

MACCABI_PCR = {"combine": "all",
               "when": [{"field": "sender", "op": "eq", "value": "מכבי"},
                        {"field": "test_type", "op": "eq", "value": "PCR"}],
               "then": {"field": "referral_number", "check": "required"}}


def test_engine_on_the_example_rule():
    def broken(**values):
        return evaluate(MACCABI_PCR, values, SENDERS_CFG)

    assert broken(sender="מכבי", test_type="PCR", referral_number=None)
    assert broken(sender="מכבי שירותי בריאות", test_type="pcr")  # alias, case
    assert not broken(sender="כללית", test_type="PCR")
    assert not broken(sender="מכבי", test_type="PCR", referral_number="R-17")
    assert not broken(sender="מכבי", test_type="סרולוגיה")


def test_spec_checks_and_hebrew_description():
    assert validate_spec(MACCABI_PCR) == []
    assert "unknown_field" in validate_spec(dict(MACCABI_PCR, when=[{"field": "kupa", "op": "eq", "value": "x"}]))
    assert "missing_arg" in validate_spec(dict(MACCABI_PCR, then={"field": "id_number", "check": "regex"}))
    text = describe_he(MACCABI_PCR)
    assert text == "כאשר גורם שולח = מכבי וגם סוג בדיקה = PCR ← מספר הפניה: חובה"


class RuleStub:
    def __init__(self, reply):
        self.reply = reply
        self.prompts = []

    async def call_tool_text(self, prompt, tool, system=None, model=None):
        self.prompts.append(prompt)
        return self.reply


def test_parse_rule_accepts_known_terms():
    stub = RuleStub({"name": "מכבי PCR", "spec": json.loads(json.dumps(MACCABI_PCR))})
    out = asyncio.run(parse_rule("אם הקופה מכבי והבדיקה PCR – חובה מספר הפניה", stub, SENDERS_CFG))
    assert out["spec"] is not None and out["unknown_terms"] == []
    assert out["description"].startswith("כאשר גורם שולח = מכבי")
    assert "מכבי שירותי בריאות" in stub.prompts[0]  # the sender list goes in the prompt


def test_parse_rule_never_guesses_an_unknown_sender():
    spec = json.loads(json.dumps(MACCABI_PCR))
    spec["when"][0]["value"] = "קופת הגליל"
    out = asyncio.run(parse_rule("...", RuleStub({"name": "x", "spec": spec}), SENDERS_CFG))
    assert out["spec"] is None and out["unknown_terms"] == ["קופת הגליל"] and out["question"]


def test_parse_rule_alias_becomes_canonical():
    spec = json.loads(json.dumps(MACCABI_PCR))
    spec["when"][0]["value"] = "maccabi"
    out = asyncio.run(parse_rule("...", RuleStub({"name": "x", "spec": spec}), SENDERS_CFG))
    assert out["spec"]["when"][0]["value"] == "מכבי"


def _set(form_id, **values):
    with Session(db.get_engine()) as s:
        for name, value in values.items():
            s.add(Field(form_id=form_id, name=name, value=json.dumps(value, ensure_ascii=False), level="ok"))
        s.commit()


def test_dry_run_counts_and_warns_about_unread_fields(tmp_env):
    flagged_ids = []
    for i in range(3):
        _, fid, _ = _seed_form()
        _set(fid, test_type="PCR")
        flagged_ids.append(fid)
    _, other, _ = _seed_form()
    _set(other, test_type="PCR", referral_number="R1")
    with TestClient(app) as client:
        body = client.post("/api/rules/dry-run", json={"spec": MACCABI_PCR}).json()
        assert body["checked"] == 4 and body["flagged"] == 3
        assert body["by_sender"] == {"מכבי": 3}
        assert sorted(e["id"] for e in body["examples"]) == sorted(flagged_ids)
        assert {"code": "field_never_read", "field": "referral_number"} not in body["warnings"]
        nothing = dict(MACCABI_PCR, then={"field": "referral_number", "check": "forbidden"},
                       when=[{"field": "full_name", "op": "not_empty"}])
        assert {"code": "field_never_read", "field": "full_name"} in \
            client.post("/api/rules/dry-run", json={"spec": nothing}).json()["warnings"]


def test_parse_endpoint_uses_the_rules_client(tmp_env):
    app.dependency_overrides[get_rules_client] = lambda: RuleStub({"name": "r", "spec": MACCABI_PCR})
    try:
        with TestClient(app) as client:
            r = client.post("/api/rules/parse", json={"text": "אם הקופה מכבי והבדיקה PCR – חובה מספר הפניה"})
    finally:
        app.dependency_overrides.pop(get_rules_client, None)
    assert r.status_code == 200 and r.json()["spec"]["then"]["field"] == "referral_number"


def test_activation_flags_open_forms_never_approved_ones(tmp_env, as_role):
    _, waiting, _ = _seed_form(workflow="pending_approval", levels=("ok", "ok"))
    _, approved, _ = _seed_form(workflow="approved", levels=("ok", "ok"))
    for fid in (waiting, approved):
        _set(fid, test_type="PCR")
    with TestClient(app) as client:
        rule = client.post("/api/rules", json={"name": "מכבי PCR", "source_text": "...", "spec": MACCABI_PCR}).json()
        assert rule["status"] == "draft" and rule["last_dry_run"]["flagged"] == 2
        out = client.post(f"/api/rules/{rule['id']}/activate", json={"apply_open": True}).json()
        assert out["status"] == "active" and out["flagged_open"] == 1
    with Session(db.get_engine()) as s:
        assert s.get(Form, waiting).workflow == "needs_fix"
        assert s.get(Form, approved).workflow == "approved"
        fld = s.exec(select(Field).where(Field.form_id == waiting, Field.name == "referral_number")).one()
        assert fld.level == "review" and {"kind": "validation", "code": f"rule:{rule['id']}"} in json.loads(fld.reasons)
        assert s.exec(select(Field).where(Field.form_id == approved, Field.name == "referral_number")).first() is None


def test_active_rule_flags_a_newly_read_form(tmp_env):
    with Session(db.get_engine()) as s:
        r = ValidationRule(name="מכבי PCR", spec=json.dumps(MACCABI_PCR), status="active")
        s.add(r)
        s.commit()
        rule_id = r.id
    batch_id = _make_batch(tmp_env, n_files=1)
    pcr = dict(GOOD, test_type={"value": "PCR", "confidence": 0.99, "legible": True})
    asyncio.run(process_batch(batch_id, _ctx(tmp_env, StubClient(response=pcr))))
    with Session(db.get_engine()) as s:
        form = s.exec(select(Form)).one()
        fld = s.exec(select(Field).where(Field.form_id == form.id, Field.name == "referral_number")).one()
    assert fld.level == "review" and json.loads(fld.reasons) == [{"kind": "validation", "code": f"rule:{rule_id}"}]
    assert form.workflow == "needs_fix"


def test_empty_optional_fields_do_not_hold_a_form_back(tmp_env):
    batch_id = _make_batch(tmp_env, n_files=1)
    asyncio.run(process_batch(batch_id, _ctx(tmp_env, StubClient())))
    with Session(db.get_engine()) as s:
        form = s.exec(select(Form)).one()
        levels = {f.name: f.level for f in s.exec(select(Field).where(Field.form_id == form.id)).all()}
    assert levels["test_type"] == "empty" and levels["referral_number"] == "empty"
    assert form.workflow == "pending_approval"


def test_only_managers_and_admins(tmp_env, as_role):
    as_role("intake")
    with TestClient(app) as client:
        assert client.get("/api/rules").status_code == 403
    as_role("admin")
    with TestClient(app) as client:
        assert client.get("/api/rules").status_code == 200
