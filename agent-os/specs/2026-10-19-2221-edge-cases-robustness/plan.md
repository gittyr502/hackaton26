# Edge Cases & Robustness (roadmap §2ג): full scope

## Context

The roadmap's new section 2ג lists 7 edge cases raised by the user and 11 more found in the code. Today:
- An empty or damaged file fails with a technical English error.
- Every page is assumed to be a commitment (`classify.py:75`), and every page becomes its own form (`split.py`).
- Uploads go in one XHR with no retry.
- There is no per-form timeout and no API-down detection.
- Polling can overwrite a field while it is being edited (`ReviewPage.tsx:66`).
- Retry silently drops manual edits.
- There is no duplicate or concurrency protection.

Goal: handle all of these **without breaking existing behavior**. Rules:
- Old endpoints keep working.
- New DB columns are added through `_add_missing_columns` (`backend/app/db.py:40`).
- New pipeline behavior is configured in `pipeline.yaml`.
- Existing tests and stub clients keep passing unchanged.

Shaping decisions:
- All edge cases are in scope. No visuals; follow the existing design (DESIGN.MD / Stitch).
- Classification is folded into the existing orientation call: one cheap call on a thumbnail, no extra cost.
- Multi-page commitment: **automatic merge**, with manual "split" and "merge with previous".
- Several commitments on one page: **one form per commitment**, each extracted from a crop of its region, each marked for review.
- No `agent-os/standards/` folder exists, so no standards apply.

## Task 1: Save spec documentation
Create `agent-os/specs/2026-10-19-2221-edge-cases-robustness/` containing:
- `plan.md`: this plan
- `shape.md`: scope, decisions above, context
- `standards.md`: "none defined"
- `references.md`: the references below

Follow the format of the earlier specs in `agent-os/specs/`.

## Task 2: Data model & error codes (backend)
- **New columns** (`models.py` plus `db.py` `new_columns`):
  - `SourceFile`: `error_code`, `warnings` (JSON list), `sha256`, `duplicate_of_batch`, `pages_total`
  - `Form`: `error_code`, `doc_type` (default `"commitment"`), `reasons` (JSON list of form-level codes), `parent_form_id`, `region_index`, `region_box`, `premerge_fields` (JSON snapshot for un-merge), `started_at`
  - `Field`: `version` (int, default 0)
  - `Batch`: `expected_files`, `notice` (e.g. `api_unavailable`)
- **`pipeline/base.py`**:
  - `class FileProblem(ValueError)` with a `code` attribute.
  - `FormDoc` gains `doc_type`, `form_reasons: List[str]`, `region_box`, `forced_type`.
  - Existing fields are untouched.
- **Runner**: `runner.py` stores `error_code = getattr(e, "code", None)` next to the existing `error` text (`process_source_file`, `run_one`).
- **`serialize.py` `batch_detail`** exposes the new keys (additive only):
  - files: `error_code`, `warnings`, `duplicate_of_batch`
  - forms: `doc_type`, `reasons`, `parent_form_id`, `page_ids`, `region_index`, `error_code`, `started_at`
  - fields: `version`
  - batch: `notice`, `expected_files`
- **Dashboards and queues** (`api/dashboard.py:47`, the intake queue in `api/forms.py`) count only `doc_type == "commitment"` forms with `parent_form_id IS NULL`.
- **Export** already filters on approved (`serialize.py:92`). Skipped and child forms never get a workflow, so they never reach export.

## Task 3: File validation: empty, damaged, truncated, password, huge, mismatch (cases 3, 4 and extras)
- **`stages/ingest.py`**:
  - A 0-byte file raises `FileProblem("empty_file")`.
  - An unknown signature raises `FileProblem("unsupported_type")`. Keep the message text so the old behavior is the same.
- **`stages/preprocess.py`**:
  - **PDF**:
    - `fitz.open` failure → `corrupt_file`.
    - `pdf.needs_pass` → `password_protected`.
    - More than `preprocess.max_pages` (default 100) pages → `too_many_pages`.
    - Render each page in try/except: skip pages that fail and add the file warning `pages_missing`.
    - `pdf.is_repaired` → warning `file_repaired`.
    - Zero good pages → `corrupt_file`.
  - **Images**:
    - Set `Image.MAX_IMAGE_PIXELS` from config; a decompression bomb → `image_too_large`.
    - `im.load()` raising OSError → retry with `ImageFile.LOAD_TRUNCATED_IMAGES`. On success, add the form reason `truncated_image`; on failure, `corrupt_file`.
    - Downscale images whose longest edge exceeds `preprocess.max_edge_px` (6000).
  - Warnings are written to `SourceFile.warnings` through a small runner helper.
- **Server-side upload checks** (`api/batches.py`, shared helper `_accept_file`):
  - size 0 → the file is recorded as failed with `empty_file`. It does not reject the whole batch.
  - size > `settings.max_file_mb` (50) → 413
  - sniffed content not supported → recorded as failed with `unsupported_type`
  - compute `sha256`; the same hash in an earlier batch sets `duplicate_of_batch` (a warning only, never blocking)
  - The legacy multi-file `POST /api/batches` keeps its 400 for a bad extension.

## Task 4: Classify: document type, blank, continuation, regions, quality (cases 5, 6 and extras)
- **`stages/classify.py`**: keep the tool name `record_orientation`, so existing stubs still work, and add **optional** properties:
  - `doc_type`: commitment | continuation | other_medical | unrelated | blank
  - `commitments_count`
  - `regions[]`: normalized boxes
  - `quality`: good | poor
  - `cut_off`: bool

  Missing or invalid values fall back to today's defaults (commitment, 1 region). The prompt is extended accordingly.
- **Local blank check before the call**: grayscale ink ratio below `classify.blank_ink_ratio`. A blank page gets `doc_type = "blank"` and no API call.
- **Regions**: when `regions.enabled` is set and there are 2 or more regions, `Classify.run` returns a **list** of FormDocs, one per region.
  - Each region is cropped into its own PNG.
  - Each FormDoc gets `region_index`, `region_box` and the reason `multiple_commitments`.
  - The runner's existing fan-out (`runner.py:155-163`) already creates forms for outputs with `form_id=None`. The first output keeps the original `form_id`.
  - A crop that comes back to classify on retry yields one region, so retry is stable.
- `quality == poor` → form reason `poor_quality`. `cut_off` → `partial_page`.
- `forced_type` (set by the user override) skips classification.
- **Runner** (`run_one`): after a stage, if `doc.doc_type in {other_medical, unrelated, blank}`, stop the stage loop and call `save_skipped()`. That sets status `done`, stores `doc_type`, adds no fields and leaves `workflow=None`.
- **Override endpoint**: `POST /api/forms/{id}/doc-type {doc_type}` sets `forced_type` and re-runs via `retry_form`.

## Task 5: Merge continuation pages (case 5)
New module `pipeline/merge.py`, called from `process_source_file` after `run_docs` when `merge_pages.enabled` is set.
- **Automatic merge**:
  - Walk the file's forms in `page_index` order.
  - Each `continuation` form attaches to the nearest previous commitment form by setting `parent_form_id`.
  - Snapshot the parent's fields into `premerge_fields`, then merge field by field:
    - empty values are filled from the other page
    - lists are unioned
    - conflicting scalars keep the parent's value, become `review` and get the reason `pages_disagree`
  - Add the form reason `merged_pages`.
  - Recompute the workflow.
  - A continuation page with no previous form is treated as a commitment.
- **Manual merge and split**:
  - `POST /api/forms/{id}/merge-previous` runs the same function.
  - `POST /api/forms/{id}/split` restores the parent from `premerge_fields`, clears `parent_form_id`, and gives the child its own workflow.
  - Both are recorded with `audit.record`, and both return 409 on approved forms (same rule as `_get_field`).

## Task 6: Form-level reasons → workflow, duplicates, empty form
- **`app/workflow.py` `initial_workflow(levels, form_reasons=None)`**: any review-kind form reason → `NEEDS_FIX`. The default argument keeps current callers working.
- **`save_fields`** persists `doc.form_reasons`, and also adds:
  - `empty_form` when every field is empty
  - `possible_duplicate` when a `commitment_numbers` value already exists on another commitment form. This lives in a helper in `pipeline/duplicates.py`.

## Task 7: Slow scanning, API down, restart, cancel (case 2 and extras)
- **Per-form timeout**: `extract.form_timeout_seconds` (default 300).
  - In `run_one`, each stage call gets the remaining budget through `asyncio.wait_for`.
  - On timeout the form fails with code `timeout` and stays retryable.
  - `Form.started_at` is set when the form is created, so the UI can show its elapsed time.
- **API down** (`claude_client.py`):
  - `AuthenticationError`, `PermissionDeniedError`, or a 400 credit or billing error → raise `ApiUnavailable` with no retry.
  - Retries exhausted on connection errors → also raise `ApiUnavailable`.
  - In the runner, the first `ApiUnavailable` sets `Batch.notice="api_unavailable"` and calls `control.pause(batch_id)`. The affected form fails with code `api_unavailable`, the others wait at the checkpoint, and the user resumes after the problem is fixed.
- **Restart** (`main.py` `recover_interrupted`): also set `error_code="interrupted"` and `finished_at`.
- **New endpoint** `POST /api/batches/{id}/retry-failed` retries every failed form, reusing `retry_form`.
- **Cancel**: verify with a test that forms already finished stay `done` and reviewable. This is expected to hold already.

## Task 8: Per-file upload (case 1)
New endpoints. The legacy `POST /api/batches` stays as it is.
- `POST /api/batches/open {expected_files}` creates the batch with status `processing`.
- `POST /api/batches/{id}/files` accepts one file, runs `_accept_file`, and starts `process_source_file` in the background right away.
- `POST /api/batches/{id}/close` sets `expected_files` to the number of files received (used for cancel, or when some files gave up).

Refactor `process_batch` so the completion part becomes `finish_batch_if_complete(batch_id)`. It runs after each file and marks the batch `done` once every expected file has arrived and finished. `process_batch` calls the same path, so its behavior doesn't change.

## Task 9: Concurrent edits
- `PATCH /api/fields/{id}` accepts an optional `version`.
  - If it is sent and stale → 409 `{code: "conflict", by: <last editor name from AuditLog>}`.
  - A successful save increments `version`.
  - Without `version`, behavior is unchanged.

## Task 10: Frontend infrastructure
- **`lib/api.ts`**:
  - `ApiError {status, code, detail}`, thrown by `request()` and `downloadExport`. It extends `Error`, so existing `.message` usage keeps working.
  - New types for all the new keys.
  - New calls: `openBatch`, `uploadFile` (XHR with `abort()` and progress), `closeBatch`, `retryFailed`, `setDocType`, `mergePrevious`, `splitForm`, and an `updateField(id, value, version)` overload.
- **`hooks/usePolling.ts`**: add an epoch counter. An external `setData` bumps it, and responses from requests started before the latest bump are dropped. This fixes stale overwrites.
- **`ReviewPage` `FieldRow`**: an `editingRef` set on focus and cleared on blur. The `useEffect` at line 66 skips syncing the draft while editing.
- **Error codes**: a helper `errorText(t, code, fallback)` uses the `hasKey` pattern from `lib/labels.ts:7`, with keys `err.<code>`.

## Task 11: Upload page
In `UploadPage.tsx`:
- Reject size-0 files client-side (`upload.errEmpty`). Warn when `countPdfPages` returns null ("may be damaged"), but still allow the file.
- `start()`: call `openBatch(n)`, then upload the files with a concurrency of 2.
  - Each `QueueItem` gets `status`, `progress` and `attempts`.
  - **Stall detection**: no progress for 30 s → abort, show the "slow connection" pill, and retry with backoff up to 3 times. After that the file is marked failed and has a manual retry.
  - A **Cancel** button aborts everything and calls `closeBatch`.
  - Navigate to processing as soon as the first file is accepted, with the remaining uploads continuing in the background. If navigation in that case is fragile, wait until every upload has finished or failed instead.

## Task 12: Processing page (cases 2 and 7)
In `ProcessingPage.tsx`:
- Replace the disabled placeholder button (lines 359-373) with a "Start reviewing" `Link` to `/batches/{id}`. It is enabled once any form is `done`.
- `FileItem`:
  - errors through `errorText`
  - warnings shown as pills
  - the duplicate warning, with a link to the earlier batch
- **ETA**: average time per finished form × remaining forms.
- A "taking longer than usual" marker on a form when its elapsed time passes half the timeout.
- The `notice=api_unavailable` banner with a resume button.
- "Retry all failed" when the batch is done and has failures.

## Task 13: Review page (cases 5, 6, 7 and extras)
In `ReviewPage.tsx`:
- Child forms (`parent_form_id`) are hidden from navigation.
- `ImageViewer` gets an optional `pages` prop (`string[]`) plus page arrows. Existing callers are unchanged. The parent's pages come from `page_ids` through `api.imageUrl`.
- **Buttons**:
  - "Split pages" on merged forms
  - "Merge with previous" on any non-approved form
- A form-reasons banner: `multiple_commitments`, `poor_quality`, `partial_page`, `truncated_image`, `merged_pages`, `possible_duplicate`, `empty_form`.
- A "Not a commitment" group for the `other_medical` / `unrelated` / `blank` forms of each file. It shows a thumbnail, the type, and an "It is a commitment" override.
- Retry asks for confirmation when any field is `manually_corrected`.
- Field saves send `version`. On 409 conflict, show `review.conflict` with the editor's name, then refresh.
- The export page shows a warning while the batch is still processing. `ExportPage.tsx:185` already has `processingNote`, so this is a check only.

## Task 14: i18n
Add every new key to `he.ts` (the source) and to `en.ts`, `ar.ts` and `ru.ts`:
- `err.*`, `warn.*`, `formReason.*`, `docType.*`, `upload.*`, `proc.*`, `review.*`

`tsc -b` enforces that every locale has every key.

## Task 15: Tests
New `backend/tests/test_edge_cases.py`. It reuses `tmp_env`, the `StubClient` pattern (`test_pipeline_failure.py:22`), `_make_batch` and `_ctx`, extended so the stub can return classify fields.

Cases:
- an empty file
- a garbage or truncated PDF (bytes cut in half)
- a password PDF (made with fitz `encryption`)
- a blank page skipped without an API call
- `other_medical` skipped, then override → extracted
- continuation merge and conflict → `pages_disagree`, then split restores
- 2 regions → 2 forms
- timeout → `timeout` code
- auth error → batch paused with a notice
- the restart recovery code
- per-file upload endpoints and batch completion
- a stale field `version` → 409
- a duplicate hash and a duplicate commitment number
- cancel keeps done forms

## Reuse
- `classify.fix_orientation` / `_thumb_b64`: the classification call
- `pipeline/crops.py`: region cropping (check its helpers before writing new ones)
- `control.pause/checkpoint`: API-down pause
- `retry_form`: override and retry-all
- `audit.record`
- `db._add_missing_columns`
- `labels.ts` `hasKey` pattern
- `start_background` in `api/batches.py`

## Verification
1. `cd backend && pytest`: all existing tests pass unchanged, and the new test file passes.
2. `cd frontend && npx tsc -b && npm run build`.
3. `python -m eval.run`: accuracy and hidden-error numbers are no worse than before (no regression from the classify prompt change).
4. Manual run (`docker compose up` or the dev servers). Upload a mixed set:
   - a 0-byte PDF
   - a half-truncated PDF
   - a password PDF
   - a blank page
   - an unrelated document
   - a 2-page commitment
   - a photo with 2 forms
   - the same file twice

   Check the pills and messages, the review groups, merge and split, and the override. Start reviewing mid-batch and edit fields while polling runs: the drafts must survive. Throttle the network in DevTools to see the slow-upload retry. Set an invalid API key to see the pause banner.

## Deviations during implementation
- **Blank page:** the model decides (`doc_type: blank`) in the same call. The local ink check is only a safety net: a page with clear ink is never skipped as "blank" (reason `blank_uncertain`). A local-only decision would have broken the existing tests, which run on plain white images.
- **Timeout:** per stage (`extract.stage_timeout_seconds`, default 300) instead of per form, so that a form waiting in the queue behind others (concurrency 5) isn't failed for no reason.
- **Retrying a form with manual fixes:** the confirmation is in the UI only. The server API is unchanged.
- **Upload screen:** moves to the processing screen once every file has arrived or been refused with a reason. If some failed, the user chooses between "retry what failed" and "continue without them" (`close`).
