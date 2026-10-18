# Phase 2א: Users, Roles, Approval Workflow and Dashboards

## Context

The MVP has one anonymous user. Roadmap Phase 2א (`agent-os/product/roadmap.md`), due 28/10, adds three roles, each with its own personal area:
- **Intake clerk:** uploads, fixes and submits forms.
- **Approver:** approves forms, or returns them with a comment.
- **Lab manager:** sees everything, exports, reassigns work and views the dashboards.

It also adds four dashboards: backlog, auto-accuracy, problem fields and time to approval. All of it rests on a `users` table, an `audit_log` table and role-based permissions. System admin and the external sender are out of scope, to be added only if time remains.

**Decisions made in shaping:**
- **Workflow:** when the pipeline finishes a form, it goes to `pending_approval` if every field is `ok`. Otherwise it goes to `needs_fix` in the intake clerk's queue.
- **Login:** password plus JWT. The Bearer token is kept in localStorage and signed with `JWT_SECRET` from `.env`.
- **Visibility:**
  - An intake clerk sees batches they uploaded and forms assigned or returned to them.
  - An approver sees every `pending_approval` form.
  - A lab manager sees everything and can reassign forms.
- **Export:** lab manager only, and only approved forms. The page warns when a batch still has forms that aren't approved.
- **Visuals:** new screens are generated in the existing Stitch project "MediScan RTL Excel Converter".

**Key design choice:** `Form.status` keeps its meaning as the pipeline state (`pending | processing | done | failed`). A new, separate `Form.workflow` column holds `needs_fix | pending_approval | returned | approved`. This leaves the roughly 8 existing `status == "done"` checks untouched (`app/api/serialize.py`, `app/api/export.py:123`, `app/main.py:17-20`, the tests).

---

## Task 1: Save spec documentation

Create `agent-os/specs/2026-10-18-1829-roles-approval-dashboards/` with these files:
- `plan.md`: this plan.
- `shape.md`:
  - Scope: the 2א priority scope.
  - Decisions: the ones above.
  - Context: no visuals yet (they come from Stitch); the references below; alignment with the product mission. Single-user was true only for the MVP, and `audit_log` is DB data, not logs, so the rule against field values in logs still holds.
- `standards.md`: there is no `agent-os/standards/` folder, so carry over the constraints from the earlier specs:
  - Only images go to Claude.
  - Logs never contain field values.
  - Code stays Python 3.9-compatible.
  - Config lives outside the code.
  - Validation failures stay `review`.
  - New rule: every state change goes through `audit.record`.
- `references.md`: the files listed under "References" below.
- `visuals/`: PNG exports of the Stitch screens from Task 2.

## Task 2: Stitch screens

In the "MediScan RTL Excel Converter" project, apply the existing design system and generate four RTL Hebrew screens:
1. Login
2. Intake clerk "my queue", with a daily summary
3. Approver queue, with bulk approve and a return-with-comment dialog
4. Lab manager dashboard: four chart cards and a workload-per-worker table

Follow `DESIGN.MD`: mint-to-navy gradient header, 20px cards, pink reserved for "needs review". Save the exports to the spec's `visuals/` folder.

## Task 3: Backend: users, auth and audit foundation

- **`app/models.py`:**
  - `User`: id, username (unique), display_name, role (`intake | approver | lab_manager`), password_hash, active.
  - `AuditLog`: id, at, user_id, action, entity (`form | field | batch`), entity_id, before (JSON), after (JSON), comment.
  - `Batch.uploaded_by`.
  - `Form`: `workflow`, `assigned_to`, `approver_comment`.
- **`app/db.py`:**
  - Register the new columns in `_add_missing_columns()` (line 37).
  - Add `seed_users()`: when there are no users, create `intake1`, `approver1` and `manager1` with `DEMO_PASSWORD` from `.env`.
  - Add `backfill_workflow()`: forms that are `done` but have `workflow IS NULL` get the same rule as new forms.
- **`app/config.py`:** add `jwt_secret`, `jwt_ttl_hours` and `demo_password`, and add them to `.env.example`.
- **New `app/auth.py`:**
  - pbkdf2 hashing with stdlib `hashlib.pbkdf2_hmac`.
  - JWT encode and decode with PyJWT. Add PyJWT to `requirements.txt` and `pyproject.toml`; installing it needs a pip trusted-host because of HTTPS interception.
  - `get_current_user`: reads `Authorization: Bearer`, and also accepts `?token=` because `<img src>` can't send headers.
  - `require_roles(*roles)` dependency factory.
- **New `app/api/auth.py`:** `POST /api/auth/login` returns `{token, user}`; `GET /api/auth/me`.
- **New `app/audit.py`:** `record(session, user, action, entity, entity_id, before=None, after=None, comment=None)`. It adds the row to the caller's session, so the row commits together with the change.
- **`app/main.py`:** register the auth router. CORS needs no change, because Bearer tokens don't need credentials mode.

## Task 4: Backend: workflow and permissions on routes

- **`pipeline/runner.py` `save_fields`** (line 93): set `form.workflow` to `pending_approval` if every field is `ok`, otherwise `needs_fix`. Set `assigned_to` to the batch's `uploaded_by` if it is empty. `retry_form` (line 227) clears the workflow until the form finishes again.
- **Permissions on existing routes** (`Depends(require_roles(...))`):

  | Routes | Who |
  |---|---|
  | Upload (`app/api/batches.py`) | intake, lab_manager; sets `uploaded_by` |
  | Batch list and detail | intake: own batches only; approver and lab_manager: all |
  | pause / resume / cancel / delete | the owning intake clerk, or lab_manager |
  | Field patch / approve / reset and form retry (`app/api/forms.py:39-100`) | the assigned intake clerk, or lab_manager. The approver gets read-only access. |
  | Export (`app/api/export.py`) and config PUT | lab_manager |

- **Audit:** each field mutation writes `audit.record` with the before and after values, next to the existing `log_event` call.
- **New `app/api/workflow.py`:**
  - `POST /api/forms/{id}/submit` (intake): `needs_fix` or `returned` → `pending_approval`. Fields still in `review` are allowed, and the response flags them.
  - `POST /api/forms/{id}/approve` (approver): → `approved`.
  - `POST /api/forms/{id}/return {comment}` (approver; comment required): → `returned`.
  - `POST /api/forms/approve-bulk {ids}` (approver).
  - `POST /api/forms/{id}/assign {user_id}` (lab_manager).
  - `GET /api/queue/me`, by role:
    - intake: my `needs_fix` and `returned` forms, oldest first, with the comment, plus my uploads' status and today's counts.
    - approver: `pending_approval` forms, filterable by the number of `review` fields, plus my history.
    - manager: workload per user.
  - `GET /api/users` (lab_manager).
  - Every transition calls `audit.record(action="status_change", before={workflow}, after={workflow})`.
- **Export of approved forms only:** in `app/api/serialize.py`, the export and confidence row queries (lines 88, 106, 144) also filter on `Form.workflow == "approved"`. `export_summary` adds an `unapproved` count, which the Export page shows as a warning.
- **New `app/api/dashboard.py`** (lab_manager):

  | Endpoint | Returns |
  |---|---|
  | `/api/dashboard/backlog` | form count per workflow state |
  | `/api/dashboard/accuracy` | % of fields in approved forms with `manually_corrected=False`, overall and by day |
  | `/api/dashboard/problem-fields` | correction count per field name, from `audit_log` `field_corrected` rows (field name × sender, for the heatmap) |
  | `/api/dashboard/time-to-approval` | average hours from form creation to `approved`, plus the average time in each state, from consecutive `status_change` rows |

## Task 5: Frontend: auth and role-aware shell

Note: another session is adding i18n to `src/main.tsx` and `src/i18n/*` right now. Make small, merge-friendly edits there, and put new strings into `src/i18n/locales/*.ts` (Hebrew at least).

- **`src/lib/api.ts`:**
  - `request()` (line 132) adds the `Authorization` header from the stored token; a 401 clears the token and redirects to `/login`.
  - `imageUrl` appends `?token=`, and `uploadBatch`'s XHR sets the header.
  - Add the `User`, `Role`, `Workflow` and queue/dashboard types, plus the api functions for Task 4.
- **New `src/auth/AuthProvider.tsx`:** context `{user, login, logout}`, with the token in localStorage wrapped in try/catch. `RequireAuth` and `RequireRole` route guards.
- **`src/main.tsx`:** add `/login` and wrap the existing routes in the guards. Add `/me` (the personal area, which renders the page for the user's role) and `/dashboard` (lab_manager). After login, redirect to `/me`.
- **`src/components/Layout.tsx`:** replace the hard-coded user (lines 63-69) with the logged-in user, role label and logout. Add nav links by role ("my queue", "approvals", "dashboard"). The 4-step pills stay inside the batch routes.
- **New UI primitives** in `src/components/ui/`, matching the existing hand-rolled style: `input.tsx`, `card.tsx`, `badge.tsx`.

## Task 6: Frontend: personal areas, review actions, dashboard

- **New pages in `src/pages/`:**
  - `LoginPage.tsx`
  - `IntakeQueuePage.tsx`: queue sorted by age, returned forms with the approver's comment, upload status, daily summary.
  - `ApprovalQueuePage.tsx`: list, filter by number of `review` fields, select and bulk approve, history.
  - `DashboardPage.tsx`: four chart cards plus the workload table with a reassign control.
  - Poll with the existing `src/hooks/usePolling.ts`.
- **`src/pages/ReviewPage.tsx`:**
  - Show a workflow chip for each form.
  - Intake clerk: a "send for approval" button.
  - Approver: read-only fields, plus "approve" and "return with comment" buttons, the comment going through the existing `ConfirmDialog` pattern in `src/components/ui/dialog.tsx`.
  - Open it from either queue with `?form=<id>`.
- **`src/pages/ExportPage.tsx`:** show the unapproved-forms warning.
- **Charts:** add `recharts` (pinned exact version; npm needs the trusted-host or `strict-ssl` workaround). Use bars for backlog and problem fields (heatmap as a CSS grid), a line for accuracy over time, and stacked bars for time per stage. Colors come from the `index.css` tokens, with pink only for "needs review".

## Task 7: Tests

- **`tests/conftest.py`:** an autouse fixture sets `app.dependency_overrides[get_current_user]` to a lab_manager user, so existing tests keep passing. Add a fixture to switch the role.
- **New `tests/test_auth.py`:** login success and failure; JWT expiry; 401 without a token; 403 for the wrong role; `?token=` on the image route.
- **New `tests/test_workflow.py`:**
  - An all-ok form becomes `pending_approval`, a flagged form becomes `needs_fix`.
  - submit / return / approve transitions and illegal transitions (409).
  - An intake clerk can't see another clerk's batch.
  - Every transition and correction writes `audit_log`.
  - Export includes only approved forms.
- **New `tests/test_dashboard.py`:** seeded `audit_log` rows produce the expected backlog, accuracy, problem-field and time-to-approval numbers.

---

## References

| What | Where |
|---|---|
| Field mutation routes (where audit hooks go) | `backend/app/api/forms.py:60-100` |
| Form completion | `backend/pipeline/runner.py:93-106`, `retry_form` at 227 |
| Column migration pattern | `backend/app/db.py:37-50` (`_add_missing_columns`) |
| Export filtering | `backend/app/api/serialize.py:88,106,144`, `backend/app/api/export.py:106-130` |
| Test setup | `backend/tests/conftest.py` (`tmp_env`), `backend/tests/test_api.py` (`_seed`) |
| Fetch wrapper | `frontend/src/lib/api.ts:132-213` |
| Polling hook | `frontend/src/hooks/usePolling.ts` |
| Header user slot | `frontend/src/components/Layout.tsx:63-69` |
| Design tokens | `frontend/src/index.css` `@theme`, `DESIGN.MD`, `stitch_ref/*.html` |

## Verification

1. `cd backend && pytest`: existing tests plus the new auth, workflow and dashboard tests pass.
2. `docker compose up`, then the demo flow:
   - Log in as `intake1` and upload the two sample files. All-ok forms skip to approval; flagged forms appear in "my queue". Fix a form and send it for approval.
   - Log in as `approver1`. Return one form with a comment and bulk-approve the rest.
   - Back as `intake1`, the returned form shows the comment. Fix it and resubmit. As `approver1`, approve it.
   - Log in as `manager1`. The dashboard shows the backlog, accuracy, problem fields and time to approval. Reassign a form. Export contains only approved forms and warns about unapproved ones.
3. Negative checks: an expired or missing token redirects to login; `approver1` gets 403 on PATCH field and on export; `intake1` can't open another clerk's batch by URL.
4. `python -m eval.run` still produces its report (the pipeline is unchanged apart from setting the workflow).
