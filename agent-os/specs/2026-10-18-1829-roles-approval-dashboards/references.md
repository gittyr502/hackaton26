# References for Users, Roles, Approval Workflow and Dashboards

## Similar Implementations

### Field mutation routes

- **Location:** `backend/app/api/forms.py:60-100` (`update_field`, `approve_field`, `reset_field`)
- **Relevance:** this is where corrections are persisted. Audit records and permission checks go here.
- **Key patterns:** `_get_field` 404 helper; each route calls `log_event` after its commit.

### Form completion in the pipeline

- **Location:** `backend/pipeline/runner.py:93-106` (`save_fields`), `retry_form` at 227, `_update` at 66
- **Relevance:** the initial workflow state is set here.

### Column migration

- **Location:** `backend/app/db.py:37-50` (`_add_missing_columns`), `init_db` at 27
- **Relevance:** new columns on existing tables must be registered here. Seeding and backfill hooks go in `init_db`.

### Export and stats

- **Location:** `backend/app/api/serialize.py:88,106,144`, `backend/app/api/export.py:106-130`
- **Relevance:** the approved-only filter and the unapproved-forms warning go here.

### Tests

- **Location:** `backend/tests/conftest.py` (`tmp_env`), `backend/tests/test_api.py` (`_seed`, `TestClient(app)`)
- **Relevance:** auth is overridden through `app.dependency_overrides`, and data is seeded by inserting rows directly.

### Frontend

- **API client:** `frontend/src/lib/api.ts:132-213`. Its `request()` wrapper gets the auth header.
- **Polling:** `frontend/src/hooks/usePolling.ts`, used by the queue and dashboard pages.
- **Header user slot:** `frontend/src/components/Layout.tsx:63-69`.
- **UI primitives:** `frontend/src/components/ui/` (button, dialog `ConfirmDialog`, tooltip, progress).
- **Design:** `frontend/src/index.css` `@theme` tokens, `DESIGN.MD`, `stitch_ref/*.html`.
