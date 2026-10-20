# Roadmap 2ד: Speed, User Admin, Patient File, Natural-Language Rules

## Context
The roadmap's new section 2ד (`agent-os/product/roadmap.md`) has four parts, and the user asked for all of them ("הכל"):

1. **Processing is very slow.** Exploration found why:
   - A typical page makes about 10 Claude calls, all on `claude-opus-5-5`, in 4 rounds that run one after another: classify, extract, localize (up to 6 calls), then double check (2–5 calls).
   - Only 5 calls run at a time for the whole process (`claude_client.py:70-75`).
   - There is no prompt caching.
   - Crops are sent as PNG cut from full-resolution pages (up to 6000 px), and the "page halves" re-read runs one half after the other.
   - A form becomes visible only after the whole chain ends (`runner.save_fields`).
   - The 1-second poll (`serialize.batch_detail`) loads every image and file blob in the batch.

   The user wants every page sent at once and the ability to correct a page while later pages are still being read.
2. **User CRUD** for an admin, with roles. A user can hold several roles.
3. **Patient file**: every commitment and referral for one ID number.
4. **Free-Hebrew validation rules.** Claude turns the text into a structured rule, and a dry run on existing data reports "הכלל היה מסמן 23 טפסים" before the rule is turned on.

Shaping decisions (user-confirmed):
- Every speed lever is allowed.
- Add the fields `test_type` and `referral_number` to extraction.
- Read referral pages (`other_medical`) lightly with a fast model so they can be linked to a patient.
- Regenerate the 4 Stitch screens during execution.
- There is no `agent-os/standards/` folder, so constraints carry over from earlier specs:
  - Python 3.9 typing.
  - Config lives in YAML.
  - Every new DB column goes in `_add_missing_columns`.
  - Every change is written with `audit.record` in the same commit.
  - Problems are stored as codes.
  - Every i18n key exists in all 4 locales.
  - Logs carry no field values.
  - Existing tests and stub clients keep passing.

---

## Task 1: Save spec documentation
Create `agent-os/specs/2026-10-19-<HHMM>-speed-users-patients-rules/`, using the time of execution, with these files. Follow the format of `agent-os/specs/2026-10-19-2221-edge-cases-robustness/`.
- `plan.md`: this plan.
- `shape.md`: scope, the decisions above, and context.
- `standards.md`: the constraints carried over.
- `references.md`: the references listed at the end of this plan.
- `visuals/`: filled in by Task 2.

## Task 2: Stitch designs (visuals)
- **Where**: project `4499292770114359296`, design system `assets/8849c62b3fe84eddbf07204131ae994f`.
- **What**: generate the 4 screens **one at a time**. Reuse the prompts from the earlier attempt: live review while processing, user management, patient file, validation rules.
- **On timeout**: don't retry. Poll `list_screens` or `get_screen` for the new title.
- **Save**: download each screenshot to `visuals/` and record the screen IDs in `references.md`.
- **If Stitch keeps failing**: carry on and build from the existing design system (Heebo, mint and navy, berry pink only for "needs review").

---

## Part A: Speed

### Task 3: Claude client, with a model per stage, adaptive concurrency and caching
**`backend/pipeline/claude_client.py`**
- Replace the fixed `Semaphore` with an `AdaptiveLimiter`:
  - Start at `extract.concurrency`, raised to 16 in `pipeline.yaml`.
  - On `RateLimitError`, halve the limit (minimum 2) and wait for `retry-after` if the header is present.
  - After N successes in a row, add 1, up to the configured maximum.
  - Turn on with `extract.adaptive: true`.
- `call_tool(..., model: Optional[str] = None)`: when `model` is given it overrides `self.model`.
- **Prompt caching**: send `system` as a list of text blocks with `cache_control: {"type": "ephemeral"}` on the last block, and add `cache_control` to the last tool. The content stays the same; only the shape changes.
- New `call_tool_text(prompt, tool, system=None, model=None)`: text only, with the same retry and error handling (`ApiUnavailable`). Used by Task 13.

**`backend/pipeline/base.py`**
- New helper `Context.call_tool(stage, **kw)`. It looks up `ctx.models.get(stage)` and passes `model=` only if the client's `call_tool` accepts it (checked with `inspect.signature` and cached).
- This keeps the duck-typed test stubs working (`test_pipeline_failure.py:21`, `test_edge_cases.py:33`).
- Each stage switches from `ctx.client.call_tool` to `ctx.call_tool("<stage>", ...)`: classify, extract, localize, double_check, plus document in Task 11.

**`config/pipeline.yaml`**, new `models:` block:
```yaml
models:
  classify: claude-haiku-5-5
  localize: claude-haiku-5-5
  document: claude-haiku-5-5
  extract: null        # null = settings.claude_model (Opus)
  double_check: null
  rules: null
```
`runner.build_context` reads it into `ctx.models`.

### Task 4: Fewer and lighter calls
- **`backend/pipeline/crops.py`**: `crop_b64` and the page halves return JPEG at quality 90, longest edge at most 1568 px, in place of PNG.
- **`confidence.py:62-63`**: re-read the two page halves in parallel with `asyncio.gather`, not one after the other.
- **Stage order** in `pipeline.yaml`: Normalize → **Validate → Localize** → Confidence. Validate is local and doesn't need tight boxes. This order lets the early save in Task 5 happen right after Validate.

### Task 5: Show each page early, finish checking it in the background
`backend/pipeline/runner.py` and `models.py`.

**New setting and columns**
- `pipeline.yaml`: `early_save: {enabled: true, after: validate}`.
- `Form.refining: bool = False`, added in `models.py` and in the `db.py` `new_columns`.

**`run_one`**
- Once the stage named in `after` finishes, and the form is a commitment with a `form_id`, call `save_fields(form_id, doc, provisional=True)`.
- Provisional levels come from `confidence.base_level` and `apply_lessons`, which are pure functions already there.
- Set `status="done"` and `refining=True`.
- The rest of the chain (Localize, then Confidence with the double check) keeps running in the same task.

**New `refine_fields(form_id, doc)`**, called in place of the final `save_fields` when a provisional save already happened. It updates rows in place and never deletes them:
- **Skipped fields**: any field with `manually_corrected`, with an approval, or whose `version` changed since the provisional save. The user's work always wins.
- **Updated fields**: everything else gets its value, level, reasons, box and `box_verified` from the final result, and `version += 1`.
- **Workflow**: recompute `initial_workflow` only when no field was touched and the form's workflow is still the one set by the provisional save. Write an audit entry only if the workflow changed.
- Finally set `refining=False`.

**Other**
- `retry_form` and the existing tests keep working: when early save is disabled, the path is the same as today.
- **Ordering**: `on_progress(0)` fires at the provisional save, so the progress bar counts forms that are ready for review.

### Task 6: Cheap polling plus SSE
- **`serialize.batch_detail`**: load `Form` and `SourceFile` with `sqlalchemy.orm.defer(Form.image_data)` and `defer(SourceFile.content)`, so no image or file blobs are read on every poll.
- **New `backend/app/events.py`**: an in-process registry of `batch_id → (version: int, asyncio.Condition)`.
  - `bump(batch_id)` is thread-safe via `loop.call_soon_threadsafe`, because the runner helpers run in threads.
  - The runner calls `events.bump` in `_update`, `_create_form`, `save_fields`, `refine_fields` and `save_skipped`.
  - `forms.py` calls it on field PATCH and approve.
- **New endpoint `GET /api/batches/{id}/events`**:
  - A `StreamingResponse` with `text/event-stream`.
  - Sends `event: changed\ndata: {version}` on every bump, and a heartbeat every 15 s.
  - Auth comes from `?token=`, which `get_current_user` already supports, and is checked with `check_batch_view`.
- **Frontend `usePolling.ts`**:
  - New option `events?: string` (a URL). It opens an `EventSource` and triggers an immediate fetch on each `changed` event.
  - While SSE is connected the polling interval drops back to 5 s. If SSE fails, it falls back to 1 s.
  - The existing stale-response and `localEdit` guards stay as they are.

### Task 7: Review while processing (`ReviewPage.tsx`, `ProcessingPage.tsx`)
- **ProcessingPage**: auto-navigate to `/batches/{id}?form=<first ready>` as soon as the first form is ready (provisional). There is a "stay on this screen" toggle, remembered in localStorage.
- **ReviewPage, top**: a progress strip "12 מתוך 30 עמודים מוכנים · זמן משוער…" while the batch is processing. Reuse the ETA calculation from `ProcessingPage.tsx:104-114`.
- **ReviewPage, form list**: a status chip on each form: בתור / בקריאה / מוכן לבדיקה / נבדק / בדיקה כפולה ברקע (`refining`).
- **Enter on the last review field** (`goToNext`, `:370-383`): if no next form is ready but some are still processing, show "העמוד הבא בקריאה…" and jump to that form automatically when it becomes ready, but only if the user hasn't navigated away.
- **New form ready**: a toast "עמוד N מוכן לבדיקה". Selection and drafts don't move; the existing `editing` ref guard already protects the field being edited.
- **i18n**: new file `frontend/src/i18n/locales/speed.ts`, following the same pattern as `edge.ts` (spread into he/en/ar/ru).

### Task 8: Speed tests and measurement
New `backend/tests/test_speed.py`:
- **Limiter**: it halves on 429 and grows back after successes. Uses a FakeMessages client like `test_claude_client.py:18-33`.
- **Model routing**: `ctx.call_tool("classify")` passes the Haiku model to a client that accepts `model`, and a stub without `model` still works.
- **Caching**: `cache_control` is present in the request kwargs.
- **Early save**:
  - With a stub client that blocks the double-check call on an `asyncio.Event`, the form is `done` with `refining=True` and fields readable via `GET /api/batches/{id}` before the double check finishes.
  - After the double check finishes, `refining=False`.
  - A field PATCHed during refining keeps the user's value.
- **Blobs**: `batch_detail` doesn't load blobs. Check that `image_data` is not in the loaded state, or count bytes.
- **Events**: the endpoint emits `changed` after `events.bump`.

Manual measurement: time the two sample files before and after on the real API. Run `python -m eval.run` with the Haiku settings. If hidden errors go up, set the offending stage back to `null` (Opus) in `pipeline.yaml`.

---

## Part B: User management

### Task 9: Multi-role backend
**`models.py` User**
- `roles: str` holds a JSON list. `role` stays as the primary role for backward compatibility.
- New columns: `token_version: int = 0`, `created_at`, `updated_at`. All added via `_add_missing_columns`.
- `db.py` migration: backfill `roles = [role]`. A new `ensure_admin()` creates `admin1` with `demo_password` and role `admin` if there is no active admin. It runs after `seed_users()`.

**`backend/app/auth.py`**
- `ROLE_ADMIN = "admin"`, added to `ROLES`.
- New helpers:
  - `roles_of(user) -> List[str]`
  - `has_role(user, *roles) -> bool`
  - `primary_role(roles)`, picked by priority: admin > lab_manager > approver > intake.
- `require_roles` checks whether the user's roles intersect the allowed ones.
- `create_token` adds `"tv": user.token_version`, and `get_current_user` returns 401 when it doesn't match. A password reset, a role change or a deactivation bumps `token_version`.
- `user_dict` adds `roles` and `active`.
- `ROLE_PERMISSIONS`: a static matrix of permissions per role, used for display only.

**Replace every `user.role ==` / `in` check with `has_role`.** The full list is from exploration:
- `api/batches.py:87,101,168,192`
- `api/config.py:25`
- `api/workflow.py`: the ~16 places at `:93…287`, including the `workload()` branch
- the ownership helpers at `auth.py:84-117`

Admin does **not** inherit lab_manager. A person who needs both gets both roles.

**New `backend/app/api/users.py`**, prefix `/api/admin/users`, `require_roles(ROLE_ADMIN)`:
- `GET` with `q`, `role` and `active` filters.
- `POST`: create with `username`, `display_name`, `roles` and `password`. Returns 409 if the username is taken.
- `PATCH /{id}`: change `display_name`, `username`, `roles` or `active`.
- `POST /{id}/reset-password`: sets a new password.
- `DELETE /{id}`: soft delete, meaning `active=False` and `token_version += 1`.
- `GET /api/admin/roles`: returns `ROLE_PERMISSIONS`.

Rules for these endpoints:
- Every change goes through `audit.record(s, admin, "user_created" | "user_updated" | "user_deactivated" | "password_reset", "user", id, before, after)`. The password hash never appears in an audit entry.
- **Guard**: deactivating the last active admin, or removing its admin role, is refused with error code `last_admin` (409).
- Register the router in `main.py:8,50-57`.

**`backend/tests/conftest.py`**: `ensure_user` sets `roles=[role]`, and an `"admin"` key is added.

### Task 10: User management screen (frontend)
**`frontend/src/lib/api.ts`**
- `Role` gains `"admin"`.
- `User` gains `roles: Role[]` and `active`.
- New `api.admin.users.*` calls.

**Role checks in the UI**
- **`AuthProvider.tsx`**: `RequireAuth` checks role intersection, and `homeFor` takes the highest-priority role (admin goes to `/admin/users`).
- **`Layout.tsx`**: build the nav as the union of `ROLE_LINKS` over all of the user's roles, and add admin links. The role label lists all roles.
- **Other single-role checks**: update `workflow.tsx:138-148` and `MePage.tsx`.

**New `frontend/src/pages/UsersPage.tsx`** at route `/admin/users` in `main.tsx`:
- Search box, role filter chips and an active/inactive toggle.
- A table of users.
- An edit drawer built on `@radix-ui/react-dialog`, with role checkboxes, an active toggle and a reset-password button.
- A collapsible read-only permissions matrix.
- `ConfirmDialog` before deactivating a user.
- `ApiError.code === "last_admin"` is shown translated.

**i18n**: new `locales/users.ts`.

Tests in `backend/tests/test_users.py`:
- CRUD.
- The last-admin guard.
- An old token stops working after deactivation or a password reset.
- Multi-role access: an approver who is also intake can do both.
- A non-admin gets 403.
- Audit entries contain no hash.

---

## Part C: Patient file

### Task 11: Patient linking and referral reading (backend)
**New `Form` columns**
- `patient_id`: the ID number, normalized and padded with `zfill(9)`. Indexed.
- `patient_link`: `auto` | `suggested` | `manual` | `rejected`.
- `doc_meta`: JSON holding `{id_number, full_name, doc_date, doc_kind, test_type, referral_number}` for non-commitment pages.

**New `backend/app/patients.py`, `link_patient(s, form)`**
- Takes the ID from the `id_number` field (commitments) or from `doc_meta` (documents).
- A valid checksum and level `ok` gives `auto`. Anything else with a value gives `suggested`.
- It never overwrites `manual` or `rejected`.
- It is called in `save_fields`, `refine_fields` and `save_skipped`, and from `PATCH /api/fields/{id}` when the changed field is `id_number`.
- A backfill for existing forms runs in `init_db`.

**Referral reading**
- New `backend/pipeline/stages/document.py`, `async read_document(doc, ctx)`. It makes one `ctx.call_tool("document", ...)` call with a small `record_document` tool on the 900 px thumbnail; reuse the encoder in `classify.py:73-79`.
- In `runner.run_one`, before `save_skipped`, call it when `doc.doc_type == "other_medical"` and `pipeline.yaml documents.read: true`.
- Any failure is swallowed and logged with no values; the page is still saved as skipped.
- `save_skipped` stores `doc_meta`.

**New `backend/app/api/patients.py`**, open to intake, approver, lab_manager and admin:
- **`GET /api/patients?q=`**: searches by ID (digits), name (normalized `values_equal` or substring match on `full_name` and `doc_meta.full_name`) or commitment number. Returns `[{patient_id, names, commitments, documents, last_seen}]`.
- **`GET /api/patients/{pid}`** returns:
  - a header with the names seen;
  - commitments: the `form_summaries` shape plus `receipt_date`, `sender`, `commitment_numbers` and `workflow`;
  - documents: `doc_meta` plus the form ID;
  - `suggested`: forms whose link is `suggested`.
  - It writes `audit.record(..., "patient_viewed", "patient", 0, after={"patient_id": pid})`.
- **`POST /api/forms/{id}/patient`**: body `{action: "confirm" | "reject" | "set", patient_id?}`, audited.

**Tests** in `backend/tests/test_patients.py`:
- Grouping by ID.
- A suggested link versus an automatic one.
- Manual links are not overwritten.
- A referral read by a stub `record_document` lands in the file.
- Search by name and by commitment number.
- The view is audited.

### Task 12: Patient screens (frontend)
- **New `PatientsPage.tsx`** at `/patients`: a search box and a result list.
- **New `PatientPage.tsx`** at `/patients/:pid`:
  - a header card;
  - a timeline of commitments, each with a workflow chip and a deep link `/batches/{batch_id}?form={id}` (reuse `formLink` from `IntakeQueuePage.tsx:18`);
  - a referrals and documents card with thumbnails from `/api/forms/{id}/image`;
  - a suggested-links card with confirm and reject buttons;
  - the note "הצפייה נרשמת ביומן".
- A "מטופלים" nav link for all roles.
- On ReviewPage, a "תיק מטופל" link next to the ID number field.
- i18n in `locales/patients.ts`.

---

## Part D: Free-Hebrew validation rules

### Task 13: New fields `test_type` and `referral_number`
**Registering the fields**
- `backend/app/fields.py`: add both names to `FIELD_NAMES`, and add `OPTIONAL_FIELDS = {"test_type", "referral_number"}`.
- `extract.py:19-26`: add Hebrew hints. Test type is, for example, PCR, serology or culture, written as it appears on the form. Referral number is the referral or order number.
- `frontend/src/lib/api.ts:6`: add both to `FIELD_NAMES`.
- Labels in all 4 locales.
- They are **not** added to `export.yaml`, so export is unchanged.

**An empty optional field must not hold a form back**
- `save_fields` / `refine_fields` leave out of `initial_workflow`'s levels any optional field whose level is `empty`.
- `ReviewPage` `reviewCount` is unaffected, since it counts only `review`.
- The intake queue's `flagged` counts in `workflow.form_summaries` must exclude empty optional fields.

**Other places that read fields**
- `confidence.py`: the double check for empty fields still covers only `full_name` and `id_number`.
- `eval/run.py`: skip fields that are missing from `ground_truth.csv`.

**Existing forms** get the new fields only through "נסה שוב". The UI shows them as empty.

### Task 14: Rule engine, conversion and dry run (backend)
**New model `ValidationRule`** with these columns:
- `id`, `name`
- `source_text`
- `spec` (JSON)
- `status`: `draft` | `active` | `disabled`
- `version`
- `created_by`, `activated_by`
- `created_at`, `updated_at`
- `last_dry_run` (JSON)

**New `backend/validators/rules.py`**, deterministic, with no LLM at run time.

Spec schema:
```json
{"combine": "all|any",
 "when": [{"field": "sender", "op": "eq|neq|in|contains|empty|not_empty", "value": "מכבי"}],
 "then": {"field": "referral_number", "check": "required|forbidden|regex|in_list|date_not_before", "arg": null}}
```

Functions:
- `validate_spec(spec)`: fields must be in `FIELD_NAMES` and ops must be known. Returns error codes.
- `evaluate(spec, values: Dict[str, Any], senders_cfg) -> bool` (true means violated):
  - Senders are compared through `match_sender` and canonical names.
  - Text is compared with `values_equal`, case-insensitive. "PCR" equals "pcr".
  - Multi-value fields match if any item matches.
- `describe_he(spec, labels)`: builds the Hebrew explanation, for example "כאשר גורם שולח = מכבי וגם סוג בדיקה = PCR ← השדה 'מספר הפניה' חובה", from the spec itself. What the manager sees is exactly what runs.

**New `backend/app/rules_nl.py`, `parse_rule(text, client, senders_cfg, model)`**
- Calls `client.call_tool_text` with a `record_rule` tool. The system prompt includes the field catalog: names, Hebrew labels, multi or optional, and the canonical senders with their aliases.
- The tool returns either a `spec`, or `{unknown_terms: [...], question: "..."}` when a term can't be mapped.
- Post-checks:
  - `validate_spec`.
  - Each sender value goes through `match_sender`; one that doesn't match becomes an unknown term, never a guess.
- Returns `{spec, description, unknown_terms, question}`.

**Dry run, `dry_run(s, spec, senders_cfg, limit=50)`**
- Runs over every commitment form with `status == "done"` and `parent_form_id IS NULL`, using **current** field values, so human corrections count.
- Same pattern as `pipeline/duplicates.py`: load the `Field` rows, `json.loads` the values, evaluate in Python.
- Returns:
  - `{checked, flagged, by_sender: {...}, examples: form_summaries[:limit]}`
  - `field_coverage`: for each field the rule references, how many forms have a value.
  - When a referenced field has a coverage of 0, add the warning code `field_never_read`. The UI shows "השדה 'סוג בדיקה' עוד לא נקרא מהטפסים".

**In the pipeline**
- `build_context` loads the active rules into `ctx.rules`, never failing the batch (same pattern as `_load_lessons`, `runner.py:55-64`).
- `stages/validate.py`: for each violated rule, `fields[then.field].add_reason("validation", f"rule:{id}")`. The field moves to `review`, because validation reasons are never soft (`confidence.py:98-101`). Values are never changed.
- `serialize.batch_detail` adds `rule_names: {id: name}` so the UI can label `rule:*` reasons.

**New `backend/app/api/rules.py`**, open to lab_manager and admin:
- `GET /api/rules`
- `POST /api/rules/parse` with `{text}`
- `POST /api/rules/dry-run` with `{spec}`
- `POST /api/rules`: create a draft
- `PATCH /api/rules/{id}`: editing bumps `version`
- `POST /api/rules/{id}/activate` with `{apply_open: bool}`. When `apply_open` is true, the rule reason is added to forms in `needs_fix` or `pending_approval` that violate it. A form in `pending_approval` moves to `needs_fix` through `transition` or audit. Approved forms are never touched.
- `POST /api/rules/{id}/disable`

All of these are audited.

**Tests** in `backend/tests/test_rules.py`:
- The engine on the example rule: Maccabi + PCR + empty referral is flagged; Clalit is not; Maccabi with a referral number is not.
- An alias "מכבי שירותי בריאות" matches.
- `parse_rule` with a stub `call_tool_text`, including an unknown sender turning into an unknown term.
- A dry-run count on seeded forms.
- The `field_never_read` warning.
- An active rule flags a newly processed form through the stub pipeline.
- `apply_open` doesn't touch approved forms.
- Empty optional fields keep a form in `pending_approval`.

### Task 15: Rules screen (frontend)
**New `RulesPage.tsx`** at `/rules`, for lab_manager and admin:
- **Rule list**: cards with a status chip and a "flagged" count.
- **Editor**:
  - A textarea, then a "המר לכלל" button.
  - A "כך המערכת הבינה" card with the condition and action chips from `description`, and a collapsible JSON view.
  - Unknown terms are shown as a question with a link to rephrase.
  - Dry-run results: a big number "הכלל היה מסמן N טפסים" out of `checked`, a breakdown by sender, and an examples table that deep-links to forms.
  - `field_never_read` warnings.
  - Buttons: "הפעל כלל", with an "סמן גם טפסים פתוחים" checkbox checked by default; "שמור כטיוטה"; and disable.
- **Reason chips**: in `ReviewPage`, a `rule:*` reason chip shows "כלל: <name>" from `rule_names`.
- A nav link for managers and admins.
- i18n in `locales/rules.ts`.

---

## Task 16: Docs
Update `README.md`:
- the new pages and roles;
- the `models:`, `early_save`, `documents` and `adaptive` settings;
- the `admin1` demo user.

Tick off the 2ד items in `roadmap.md`.

## References (for references.md)
- **Speed**: `backend/pipeline/claude_client.py`, `runner.py` (`run_docs`, `save_fields`, `_load_lessons`), `stages/{classify,extract,localize,confidence}.py`, `crops.py`
- **Polling and review**: `frontend/src/hooks/usePolling.ts`, `pages/ProcessingPage.tsx`, `pages/ReviewPage.tsx` (the `editing` guard, `goToNext`)
- **Analysing existing data and exposing it through an API**: `pipeline/learning.py` and `app/api/learning.py`; `pipeline/duplicates.py` for querying by field value
- **Validation**: `stages/validate.py`, `validators/senders.py`, `pipeline/normalizers.py`
- **Auth**: `app/auth.py` (`require_roles`, `get_current_user`), `app/audit.py`, `app/db.py` (`_add_missing_columns`, `seed_users`)
- **UI**: `DashboardPage.tsx` (manager page pattern), `IntakeQueuePage.tsx` (`formLink`), `components/ui/ConfirmDialog`, `i18n/locales/edge.ts` (pattern for extra locale files)

## Verification
1. `cd backend && python -m pytest`: everything passes, old and new.
2. `cd frontend && npm run build`: the type check confirms every i18n key exists in all 4 locales.
3. **Manual run** with `docker compose up` or a dev server, using the 2 sample files:
   - The first form is reviewable within about 15 s.
   - Editing page 1 while later pages are still being read works.
   - A field edited during "בדיקה כפולה ברקע" is not overwritten.
   - Total time is at most ⅓ of the earlier run (record both timings in the spec).
4. `python -m eval.run` with the new `models:`: no new hidden errors compared with the baseline.
5. **Users**: log in as `admin1`, create a user with intake and approver, log in as that user and see both nav sets. Deactivating the last admin is refused.
6. **Rules**: enter "אם הקופה מכבי והבדיקה PCR – חובה מספר הפניה". Check the explanation, check that the dry-run count matches a manual count, activate the rule, and see a new upload flagged with "כלל: …".
7. **Patients**: search by an ID from the samples, see the commitments and referrals, open a deep link to a form, and confirm the view appears in `audit_log`.
