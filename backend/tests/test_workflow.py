"""Approval workflow: starting state from the pipeline, transitions, visibility, audit and approved-only export."""
import asyncio
import json

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import db
from app.fields import OPTIONAL_FIELDS
from app.main import app
from app.models import AuditLog, Batch, Field, Form, SourceFile
from app.workflow import initial_workflow
from pipeline.runner import process_batch
from tests.test_pipeline_failure import GOOD, StubClient, _ctx, _make_batch


def _seed_form(uploaded_by=None, workflow="needs_fix", levels=("review", "ok"), assigned_to=None):
    with Session(db.get_engine()) as s:
        b = Batch(status="done", uploaded_by=uploaded_by)
        s.add(b)
        s.commit()
        sf = SourceFile(batch_id=b.id, filename="a.png", path="a.png", status="done")
        s.add(sf)
        s.commit()
        fm = Form(batch_id=b.id, source_file_id=sf.id, status="done", workflow=workflow,
                  assigned_to=assigned_to if assigned_to is not None else uploaded_by)
        s.add(fm)
        s.commit()
        names = ["receipt_date", "sender"]
        values = ["2026-03-01", "מכבי"]
        ids = []
        for name, value, level in zip(names, values, levels):
            fld = Field(form_id=fm.id, name=name, value=json.dumps(value, ensure_ascii=False), level=level)
            s.add(fld)
            s.commit()
            ids.append(fld.id)
        return b.id, fm.id, ids


def _workflow(form_id):
    with Session(db.get_engine()) as s:
        return s.get(Form, form_id).workflow


def _audit(action=None):
    with Session(db.get_engine()) as s:
        q = select(AuditLog)
        if action:
            q = q.where(AuditLog.action == action)
        return s.exec(q.order_by(AuditLog.id)).all()


def test_initial_workflow_rule():
    assert initial_workflow(["ok", "ok"]) == "pending_approval"
    assert initial_workflow(["ok", "review"]) == "needs_fix"
    assert initial_workflow(["ok", "empty"]) == "needs_fix"
    assert initial_workflow([]) == "needs_fix"


def test_pipeline_sets_workflow_and_assignee(tmp_env, as_role):
    clerk = as_role("intake")
    batch_id = _make_batch(tmp_env, n_files=1)
    with Session(db.get_engine()) as s:
        b = s.get(Batch, batch_id)
        b.uploaded_by = clerk.id
        s.add(b)
        s.commit()
    flagged = dict(GOOD, id_number={"value": "123456789", "confidence": 0.99, "legible": True})  # bad check digit
    asyncio.run(process_batch(batch_id, _ctx(tmp_env, StubClient(response=flagged))))
    with Session(db.get_engine()) as s:
        form = s.exec(select(Form)).one()
        assert form.workflow == "needs_fix" and form.assigned_to == clerk.id
    changes = _audit("status_change")
    assert len(changes) == 1 and changes[0].user_id is None
    assert json.loads(changes[0].after) == {"workflow": "needs_fix"}


def test_all_ok_form_skips_intake(tmp_env):
    batch_id = _make_batch(tmp_env, n_files=1)
    asyncio.run(process_batch(batch_id, _ctx(tmp_env, StubClient())))
    with Session(db.get_engine()) as s:
        levels = [f.level for f in s.exec(select(Field)).all() if f.name not in OPTIONAL_FIELDS]
        form = s.exec(select(Form)).one()
    assert all(lv == "ok" for lv in levels)
    assert form.workflow == "pending_approval"


def test_submit_return_resubmit_approve(tmp_env, as_role):
    clerk = as_role("intake")
    _, form_id, (date_id, _) = _seed_form(uploaded_by=clerk.id)
    with TestClient(app) as client:
        assert client.patch(f"/api/fields/{date_id}", json={"value": "02/03/2026"}).status_code == 200
        r = client.post(f"/api/forms/{form_id}/submit")
        assert r.status_code == 200 and r.json()["workflow"] == "pending_approval"
        assert client.post(f"/api/forms/{form_id}/submit").status_code == 409  # already submitted

        as_role("approver")
        assert client.patch(f"/api/fields/{date_id}", json={"value": "x"}).status_code == 403  # read-only
        assert client.post(f"/api/forms/{form_id}/return", json={"comment": "  "}).status_code == 422
        r = client.post(f"/api/forms/{form_id}/return", json={"comment": "בדקי את התאריך"})
        assert r.status_code == 200 and _workflow(form_id) == "returned"

        as_role("intake")
        q = client.get("/api/queue/me").json()
        assert [f["id"] for f in q["forms"]] == [form_id]
        assert q["forms"][0]["approver_comment"] == "בדקי את התאריך"
        assert q["today"]["corrected"] == 1 and q["today"]["submitted"] == 1
        assert client.post(f"/api/forms/{form_id}/approve").status_code == 403
        assert client.post(f"/api/forms/{form_id}/submit").status_code == 200

        as_role("approver")
        assert [f["id"] for f in client.get("/api/queue/me").json()["forms"]] == [form_id]
        assert client.post(f"/api/forms/{form_id}/approve").status_code == 200
        assert _workflow(form_id) == "approved"
        h = client.get("/api/queue/me").json()
        assert h["today"] == {"approved": 1, "returned": 1, "waiting": 0}

        as_role("lab_manager")
        assert client.patch(f"/api/fields/{date_id}", json={"value": "x"}).status_code == 409  # frozen

    actions = [(a.action, json.loads(a.after).get("workflow")) for a in _audit()]
    assert actions == [
        ("field_corrected", None), ("status_change", "pending_approval"), ("status_change", "returned"),
        ("status_change", "pending_approval"), ("status_change", "approved"),
    ]
    corrected = _audit("field_corrected")[0]
    assert json.loads(corrected.before)["value"] == "2026-03-01"
    assert json.loads(corrected.after)["value"] == "2026-03-02"


def test_bulk_approve_skips_forms_not_waiting(tmp_env, as_role):
    _, a, _ = _seed_form(workflow="pending_approval")
    _, b, _ = _seed_form(workflow="needs_fix")
    as_role("approver")
    with TestClient(app) as client:
        r = client.post("/api/forms/approve-bulk", json={"ids": [a, b, 999]})
    assert r.json() == {"approved": [a], "skipped": [b, 999]}
    assert _workflow(a) == "approved" and _workflow(b) == "needs_fix"


def test_intake_sees_only_own_batches(tmp_env, as_role):
    other = as_role("intake2")
    other_batch, other_form, (other_field, _) = _seed_form(uploaded_by=other.id)
    me = as_role("intake")
    my_batch, _, _ = _seed_form(uploaded_by=me.id)
    with TestClient(app) as client:
        assert [b["id"] for b in client.get("/api/batches").json()] == [my_batch]
        assert client.get(f"/api/batches/{other_batch}").status_code == 404
        assert client.get(f"/api/forms/{other_form}/image").status_code == 404
        assert client.patch(f"/api/fields/{other_field}", json={"value": "x"}).status_code == 403
        assert client.delete(f"/api/batches/{other_batch}").status_code == 403

        as_role("lab_manager")
        assert client.post(f"/api/forms/{other_form}/assign", json={"user_id": me.id}).status_code == 200

        as_role("intake")  # the reassigned form and its batch are now visible to me
        assert client.get(f"/api/batches/{other_batch}").status_code == 200
        assert other_form in [f["id"] for f in client.get("/api/queue/me").json()["forms"]]
    assert _audit("assigned")[0].entity_id == other_form


def test_assign_only_to_intake(tmp_env, as_role):
    approver = as_role("approver")
    _, form_id, _ = _seed_form()
    as_role("lab_manager")
    with TestClient(app) as client:
        assert client.post(f"/api/forms/{form_id}/assign", json={"user_id": approver.id}).status_code == 422


def test_export_contains_only_approved_forms(tmp_env):
    batch_id, approved, _ = _seed_form(workflow="approved", levels=("ok", "ok"))
    with Session(db.get_engine()) as s:
        sf = s.exec(select(SourceFile)).first()
        s.add(Form(batch_id=batch_id, source_file_id=sf.id, page_index=1, status="done", workflow="needs_fix"))
        s.commit()
    with TestClient(app) as client:
        summary = client.get(f"/api/batches/{batch_id}/export/summary").json()
    assert summary["approved"] == 1 and summary["unapproved"] == 1
    assert [row["_form_id"] for row in summary["preview"]] == [approved]


def test_manager_finalizes_batch_alone(tmp_env, as_role):
    batch_id, a, _ = _seed_form(workflow="needs_fix")
    with Session(db.get_engine()) as s:
        sf = s.exec(select(SourceFile)).first()
        s.add(Form(batch_id=batch_id, source_file_id=sf.id, page_index=1, status="done", workflow="pending_approval"))
        s.add(Form(batch_id=batch_id, source_file_id=sf.id, page_index=2, status="failed"))
        s.commit()
        b = s.exec(select(Form).where(Form.page_index == 2)).one().id
    as_role("approver")
    with TestClient(app) as client:
        assert client.post(f"/api/batches/{batch_id}/finalize").status_code == 403
        as_role("lab_manager")
        r = client.post(f"/api/batches/{batch_id}/finalize")
        assert r.status_code == 200 and r.json()["skipped"] == [b] and len(r.json()["approved"]) == 2
        summary = client.get(f"/api/batches/{batch_id}/export/summary").json()
    assert summary["approved"] == 2 and _workflow(a) == "approved"


def test_export_access_by_role(tmp_env, as_role):
    clerk = as_role("intake")
    as_role("intake2")
    batch_id, form_id, _ = _seed_form(uploaded_by=clerk.id, workflow="pending_approval", levels=("ok", "ok"))
    url = f"/api/batches/{batch_id}/export"
    with TestClient(app) as client:
        as_role("intake")
        assert client.get(url).status_code == 403  # nothing approved yet
        as_role("approver")
        assert client.get(f"{url}/summary").status_code == 200  # the approver can always look
        assert client.post(f"/api/forms/{form_id}/approve").status_code == 200
        assert client.get(url).status_code == 200  # ... and download
        as_role("intake")
        assert client.get(url).status_code == 200  # the uploader, once approved
        as_role("intake2")
        assert client.get(url).status_code == 404  # not her batch
        as_role("lab_manager")
        assert client.get(url).status_code == 200


def test_intake_uploads_show_approved_count(tmp_env, as_role):
    clerk = as_role("intake")
    mine, form_id, _ = _seed_form(uploaded_by=clerk.id, workflow="pending_approval", levels=("ok", "ok"))
    manager_batch, _, _ = _seed_form(workflow="needs_fix", assigned_to=clerk.id)  # uploaded by someone else, assigned to her
    with TestClient(app) as client:
        as_role("approver")
        assert client.post(f"/api/forms/{form_id}/approve").status_code == 200
        as_role("intake")
        uploads = {u["id"]: u for u in client.get("/api/queue/me").json()["uploads"]}
    assert uploads[mine]["approved"] == 1 and uploads[manager_batch]["approved"] == 0
