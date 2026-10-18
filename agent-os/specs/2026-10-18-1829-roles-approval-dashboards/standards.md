# Standards for Users, Roles, Approval Workflow and Dashboards

There is no `agent-os/standards/` folder in the project yet. Run `/discover-standards` to create one.

These constraints carry over from earlier specs (`2026-10-15-2332-phase1-mvp-form-extraction` and `2026-10-18-1802-handwriting-multilingual-extraction`):

- **Data sent out:** only page images (or crops of them) go to Claude. Nothing else leaves the machine.
- **Logs:** they never contain field values. `audit_log` rows live in the DB and are not logs.
- **Python compatibility:** code stays Python 3.9-compatible (Docker uses 3.12). Use `Optional[...]`, not `X | None`.
- **Config:** it lives outside the code, in YAML seeded into the DB. Secrets and demo passwords go in `.env`.
- **Validation failures:** they always stay `review`.

New in this spec:

- **Audit:** every workflow transition and every field mutation calls `audit.record(...)` in the same session and commit as the change.
- **Permissions:** they are declared per route with `Depends(require_roles(...))`. Ownership checks (uploader or assignee) live in shared helpers, not inline in each route.
- **Workflow state:** `Form.workflow` is changed only through `transition()` in `app/workflow.py`. The exceptions are the pipeline's initial assignment in `save_fields` and `retry_form` clearing it.
