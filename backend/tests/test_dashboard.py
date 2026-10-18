"""Dashboard numbers derived from seeded forms, fields and audit rows."""
import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import db
from app.main import app
from app.models import AuditLog, Batch, Field, Form, SourceFile


def _change(s, form_id, to, at, before=None, user_id=None):
    s.add(AuditLog(action="status_change", entity="form", entity_id=form_id, form_id=form_id, at=at,
                   user_id=user_id, before=json.dumps({"workflow": before}), after=json.dumps({"workflow": to})))


def _seed():
    t0 = datetime.utcnow() - timedelta(hours=10)
    with Session(db.get_engine()) as s:
        b = Batch(status="done")
        s.add(b)
        s.commit()
        sf = SourceFile(batch_id=b.id, filename="a.png", path="a.png", status="done")
        s.add(sf)
        s.commit()
        # form 1: processed in 1h -> needs_fix 2h -> pending 1h -> approved; one of 2 fields corrected
        f1 = Form(batch_id=b.id, source_file_id=sf.id, status="done", workflow="approved", created_at=t0)
        # form 2: processed in 1h -> pending 3h -> approved; untouched
        f2 = Form(batch_id=b.id, source_file_id=sf.id, page_index=1, status="done", workflow="approved",
                  created_at=t0)
        f3 = Form(batch_id=b.id, source_file_id=sf.id, page_index=2, status="done", workflow="needs_fix",
                  created_at=t0)
        f4 = Form(batch_id=b.id, source_file_id=sf.id, page_index=3, status="failed", created_at=t0)
        s.add_all([f1, f2, f3, f4])
        s.commit()
        for fm, corrected in ((f1, [True, False]), (f2, [False, False])):
            s.add(Field(form_id=fm.id, name="sender", value=json.dumps("מכבי", ensure_ascii=False), level="ok",
                        manually_corrected=corrected[0]))
            s.add(Field(form_id=fm.id, name="id_number", value=json.dumps("123456782"), level="ok",
                        manually_corrected=corrected[1]))
        h = timedelta(hours=1)
        _change(s, f1.id, "needs_fix", t0 + h)
        _change(s, f1.id, "pending_approval", t0 + 3 * h, before="needs_fix")
        _change(s, f1.id, "approved", t0 + 4 * h, before="pending_approval")
        _change(s, f2.id, "pending_approval", t0 + h)
        _change(s, f2.id, "approved", t0 + 4 * h, before="pending_approval")
        s.add(AuditLog(action="field_corrected", entity="field", entity_id=1, form_id=f1.id, at=t0 + 2 * h,
                       before=json.dumps({"name": "sender", "value": "מכב"}, ensure_ascii=False),
                       after=json.dumps({"name": "sender", "value": "מכבי"}, ensure_ascii=False)))
        s.commit()


def test_dashboards(tmp_env):
    _seed()
    with TestClient(app) as client:
        backlog = {r["state"]: r["count"] for r in client.get("/api/dashboard/backlog").json()["states"]}
        assert backlog == {"processing": 0, "needs_fix": 1, "pending_approval": 0, "returned": 0,
                           "approved": 2, "failed": 1}

        acc = client.get("/api/dashboard/accuracy").json()
        assert acc["accuracy"] == 75.0 and acc["fields"] == 4 and acc["approved_forms"] == 2
        assert len(acc["by_day"]) == 1 and acc["by_day"][0]["accuracy"] == 75.0

        pf = client.get("/api/dashboard/problem-fields").json()
        assert pf["fields"][0] == {"field": "sender", "corrections": 1}
        assert pf["cells"]["sender"] == {"מכבי": 1} and pf["senders"] == ["מכבי"]

        tta = client.get("/api/dashboard/time-to-approval").json()
        assert tta["forms"] == 2 and tta["avg_hours"] == 4.0
        stages = {r["stage"]: r["avg_hours"] for r in tta["stages"]}
        assert stages == {"processing": 1.0, "needs_fix": 1.0, "pending_approval": 2.0, "returned": 0}

        assert client.get("/api/dashboard/workload").status_code == 200
