# Phase 1 MVP: Commitment-Form Extraction

## Context

The central virology lab types every commitment form (scanned PDF, phone photo, handwriting) into Excel by hand, which is slow and error-prone. We're building the full Phase 1 MVP from `agent-os/product/`. It turns a stack of forms into an RTL Excel sheet with one row per commitment and 7 fields: first name, last name, ID, central numbers, receipt date, sender, commitment numbers. Every field gets a confidence level (ok / review / empty), and the review screen lets the single user confirm or fix fields quickly. The headline metric is **zero hidden errors**: no field marked ok whose value is wrong. The repo is empty apart from the product docs.

Decisions from shaping:
- Scope: the full Phase 1 roadmap. Build backend first, then the UI.
- No visuals or sample forms yet. The UI is designed from the roadmap.
- Excel: default Hebrew columns in field order, defined in `export.yaml`.
- Model: `claude-sonnet-5-5` by default, overridable with `CLAUDE_MODEL` in `.env`.
- Double-check: a second focused read can upgrade a field to ok **only** when both reads agree and the only weak signal was model confidence. Validation failures always stay review.
- Standards: none exist yet. Run `/discover-standards` after the build.

Spec folder: `agent-os/specs/2026-10-15-2332-phase1-mvp-form-extraction/`

---

## Task 1: Save spec documentation

Create the spec folder with:
- `plan.md`: this plan
- `shape.md`: scope, the decisions above, context (Visuals: none; References: none, the repo is empty; Product alignment: full)
- `standards.md`: notes that no standards exist yet and lists the conventions taken from `tech-stack.md` (Stage protocol, config outside code, logs hold no field values)
- `references.md`: no in-repo references; points to `agent-os/product/*.md`
- No `visuals/` folder, since no visuals were provided

## Task 2: Repo skeleton and config

```
backend/  app/ pipeline/ validators/ export/ tests/  pyproject.toml  Dockerfile
config/   pipeline.yaml  senders.yaml  export.yaml
eval/     run.py  ground_truth.csv (header only)  samples/
frontend/ (Vite React TS)
data/     (gitignored)
docker-compose.yml  .env.example  .gitignore  README.md
```
- `backend/app/config.py`: Pydantic `Settings`. Reads `.env` (`ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `DATA_DIR`) and loads the 3 YAML files.
- `pipeline.yaml`: ordered stage list (`module:Class`), `extract.concurrency` (default 5), `extract.max_retries`, `confidence.threshold` (for example 0.85), `double_check.enabled`.
- `senders.yaml`: canonical sender names with aliases, plus the fuzzy-match threshold.
- `export.yaml`: column order, Hebrew headers, sheet name, date format, multi-value separator.
- Logging helper that logs only IDs and statuses, never field values.

## Task 3: Database (SQLite via SQLModel)

`backend/app/models.py`:
- `Batch`: id, created_at, status
- `SourceFile`: id, batch_id, filename, path, mime, status, progress, error
- `Form`: id, batch_id, source_file_id, page_index, image_path, status (`pending|processing|done|failed`), error
- `Field`: id, form_id, name, value (JSON text, so multi-value fields are stored as lists), raw_value, confidence (float), level (`ok|review|empty`), reasons (JSON list), manually_corrected (bool)

`backend/app/db.py`: engine at `data/app.db`, `create_all` on startup, session dependency.

## Task 4: Pipeline core and the 8 stages

`backend/pipeline/base.py`:
- `FormDoc`: a Pydantic working object holding the file or page image path, fields dict, and reasons.
- `Context`: settings, Claude client, batch id.
- `Stage(Protocol)`: `run(form, ctx) -> FormDoc | list[FormDoc]`. The list return lets `split` fan out pages.

`backend/pipeline/runner.py`:
- Loads the stage classes from `pipeline.yaml` and runs each source file through them.
- Persists Forms and Fields and updates per-file progress.
- Wraps each form in try/except, so a failed form is marked `failed` with its error and the rest of the batch keeps going.
- `retry_form(form_id)` re-runs the stages from `classify` onward on the stored page image.
- Runs as an asyncio background task started from the upload endpoint. A semaphore enforces `extract.concurrency`.

Stages in `backend/pipeline/stages/`, one file each:
1. `ingest.py`: save the upload under `data/batches/{batch}/`, sniff the type, and convert HEIC with `pillow-heif`.
2. `preprocess.py`: render PDF pages at 200 DPI with PyMuPDF and apply `ImageOps.exif_transpose` to images. Output is PNGs.
3. `split.py`: one page becomes one FormDoc (MVP).
4. `classify.py`: pass-through that tags `form_type="commitment"`. This is the Phase 2 hook.
5. `extract.py`:
   - Sends only the page image (base64) to Claude with a forced `tool_choice` on a `record_form` tool.
   - Each field returns `{value|null, confidence 0–1, legible bool}`. Central numbers and commitment numbers come back as arrays.
   - The prompt says to return null rather than guess.
   - Retries with exponential backoff and jitter on 429, 5xx and timeouts.
6. `normalize.py`:
   - Trim and collapse whitespace.
   - ID: digits only, left-pad to 9.
   - Dates: parse common formats to ISO.
   - Multi-values: split on comma, newline or whitespace, then dedupe.
   - Sender: fuzzy match against names and aliases with `rapidfuzz`. Keep the raw value in `raw_value`.
7. `validate.py`, using `backend/validators/`:
   - `israeli_id.py`: Luhn-style check digit.
   - `dates.py`: valid date, not in the future.
   - `senders.py`: the value must be canonical. A match below the threshold keeps the value and adds the reason `sender_not_in_list`.
   - Each failure appends a reason with kind `validation`.
8. `confidence.py`:
   - A null value gives `empty`.
   - Otherwise the level is the minimum of: model confidence vs threshold, legibility, and validation.
   - If `double_check.enabled` and the level isn't ok, run a second focused Claude call for just those fields. If it disagrees, keep review and add a reason. If it agrees and the only reasons are soft (confidence or legibility), upgrade to ok.

## Task 5: API (FastAPI)

`backend/app/main.py` plus routers in `backend/app/api/`:
- `POST /api/batches`: multipart upload of PDF, JPG, PNG or HEIC files. Creates the batch and starts processing.
- `GET /api/batches`, `GET /api/batches/{id}`: status, per-file progress, forms with fields. The UI polls this every 1s.
- `DELETE /api/batches/{id}`: deletes the DB rows and `data/batches/{id}/`.
- `GET /api/forms/{id}/image`: the page PNG.
- `POST /api/forms/{id}/retry`: re-runs one form.
- `PATCH /api/fields/{id}` `{value}`: saves the value, sets `manually_corrected=true` and `level=ok`.
- `POST /api/fields/{id}/approve`: sets `level=ok` and keeps the value.
- `GET /api/batches/{id}/export/summary`: count of remaining review fields, for the warning.
- `GET /api/batches/{id}/export`: the xlsx download.

## Task 6: Excel export

`backend/export/excel.py` with openpyxl:
- Sheet set to `rightToLeft=True`, one row per form, columns and headers from `export.yaml`.
- ID written as a string with cell format `@`, so leading zeros survive.
- Dates as `DD/MM/YYYY` text.
- Multi-values joined with `", "`.

## Task 7: Eval script

`eval/run.py` (`python -m eval.run`):
- Runs the pipeline on `eval/samples/` without the DB and compares against `eval/ground_truth.csv` (filename, page, 7 fields; multi-values separated by `;`).
- Reports, printed and saved to `eval/report.md`:
  - per-field accuracy after normalization
  - **hidden errors** (level ok but value wrong)
  - flag rate
  - false empty (empty, but the ground truth has a value)
- The 10–15 sample forms and their ground truth must come from the lab. Until then the script runs on whatever is present.

## Task 8: pytest

`backend/tests/`:
- `test_normalize.py`: IDs, dates, multi-value splitting.
- `test_israeli_id.py`: valid and invalid check digits.
- `test_sender_match.py`: exact, alias, fuzzy, and no match.
- `test_export.py`: generate an xlsx, reopen it, and assert RTL, the ID as text with a leading zero, the date format, and comma joining.
- `test_pipeline_failure.py`: a stubbed extract raises on one form and the batch still completes.
- The Claude client is mocked in all tests.

## Task 9: Frontend

Vite, React, TypeScript, Tailwind and shadcn/ui. The root has `dir="rtl"` and `lang="he"` with a Hebrew font. Orange is reserved for review.
- `api.ts`: typed fetch client and a `usePolling` hook (1s, stops once all forms are done or failed).
- **Upload** screen: drag-and-drop of one or many files, per-file progress bars, then navigation to Review.
- **Review** screen:
  - TanStack Table with one row per form and 7 editable cells.
  - Review cells have an orange background, empty cells are visibly blank, and each cell has a tooltip with its reasons.
  - Image panel beside the table using `react-zoom-pan-pinch` plus a rotate button.
  - "Review only" filter.
  - Inline edit saves immediately through PATCH.
  - **Enter** approves or saves and jumps to the next review cell.
  - Failed forms show a "נסה שוב" (Try again) button.
- **Export** screen and action: shows the remaining review count with a confirmation warning when it's above 0, downloads the xlsx, and has a batch delete with a confirmation.

## Task 10: Docker Compose and README

- `backend/Dockerfile`: python:3.12-slim running uvicorn.
- `frontend/Dockerfile`: a node build stage, then nginx serving static files and proxying `/api` to the backend.
- `docker-compose.yml`: both services, the `./data` and `./config` volumes, and `env_file: .env`.
- README: setup (copy `.env.example`, add the key), `docker compose up`, `pytest`, `python -m eval.run`.

---

## Verification

1. `pytest backend/tests` passes.
2. `docker compose up` brings up both services, and the UI loads RTL at http://localhost.
3. Upload 2 sample files (any test forms until the lab provides real ones) in one action. Progress bars complete and the table shows all 7 fields, with every central number and commitment number kept.
4. Uploading a form with a bad ID check digit gives an orange ID cell. An unknown sender is orange or set to its canonical value.
5. Edit a field and refresh the page: the edit persists.
6. Force an extract failure (for example a bad API key for one run): the form shows failed and "נסה שוב" re-runs it.
7. Export with orange fields left shows the warning. The xlsx opens in Excel RTL, with the ID as text and dates as DD/MM/YYYY.
8. `python -m eval.run` writes `eval/report.md` with the 4 metrics.
9. Deleting a batch removes its rows and the `data/batches/{id}` folder.
10. Timing check: 30 forms from upload to export in about 4 minutes.
