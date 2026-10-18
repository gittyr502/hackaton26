# Handwriting support in Hebrew, English, Arabic and Russian, plus a full-name field

## Context

When a field on a commitment form is handwritten (for example the patient's name or ID in blue pen, as in the sample `gggg.pdf`), the value is not extracted and the field comes back empty. Exploring the code found three causes. There is no OCR step and no PDF text layer, so neither is the cause.

1. **The prompt pushes Claude to null.** `SYSTEM` says "not sure of every character, return null" and mentions only Hebrew ([extract.py:26-31](backend/pipeline/stages/extract.py#L26-L31)).
2. **The resolution is low.** The full page is shrunk to a 1568px long edge (about 134 DPI) ([extract.py:14](backend/pipeline/stages/extract.py#L14)), so faint, small handwriting is lost.
3. **Empty fields are never re-read.** The double-check runs only on `review` fields and only sees the shrunk full page ([confidence.py:40-51](backend/pipeline/stages/confidence.py#L40-L51)).

Decisions from shaping:
- **Value plus review:** handwriting gets the best reading and is marked for review. The headline metric stays zero hidden errors.
- **Prompt, resolution and crops:** fix the prompt and re-read handwritten fields from a zoomed crop.
- **One full-name field:** `full_name` replaces `first_name` and `last_name`. Total fields go from 7 to 6.
- **ID without a leading zero:** "11223344", not "011223344". The check-digit validation pads internally.

Spec folder: `agent-os/specs/2026-10-18-1802-handwriting-multilingual-extraction/`

---

## Task 1: Save spec documentation

Create the spec folder with the following:
- **plan.md**: this plan.
- **shape.md**: scope, the decisions above, root causes, and product alignment.
  - Product alignment: the mission says "an empty field beats a guess" and "zero hidden errors". This plan keeps that, because an uncertain reading is always `review` and never `ok`.
- **standards.md**: `agent-os/standards/` doesn't exist. Note that, plus the constraints from the Phase 1 spec: only page images go to Claude, logs hold no field values, and the code stays Python 3.9-compatible.
- **references.md**: `extract.py`, `confidence.py`, `normalizers.py`, `validate.py`/`israeli_id.py`, `eval/run.py`, and the Phase 1 spec.
- **visuals/gggg.pdf**: copied from `data/batches/3/uploads/1_gggg.pdf`.

## Task 2: Merge the names into `full_name`

**Backend**
- [fields.py](backend/app/fields.py): replace `first_name` and `last_name` with `full_name` (6 fields). Update the docstring.
- [extract.py](backend/pipeline/stages/extract.py) `FIELD_HINTS`: `"full_name": "שם מלא של המטופל/ת (פרטי + משפחה) כפי שכתוב — מודפס או בכתב יד, בכל שפה"`.

**Export config**
- [config/export.yaml](config/export.yaml): one `full_name` column with the header "שם מלא".
- Migration in [db.py](backend/app/db.py): the DB copy of the config takes precedence over the YAML. Add `migrate_config()`, called next to `seed_config()`. If the stored `export` config has `first_name`/`last_name` columns, replace them with a single `full_name` column at the position of the first one.

**Frontend**
- [api.ts](frontend/src/lib/api.ts) `FIELD_NAMES`, [labels.ts](frontend/src/lib/labels.ts) (`full_name: "שם מלא"`).
- [ReviewPage.tsx:19](frontend/src/pages/ReviewPage.tsx#L19) group: `["full_name", "id_number"]`.
- [ExportPage.tsx:9](frontend/src/pages/ExportPage.tsx#L9) `NAME_FIELDS`.

**Old batches** in the DB keep their first/last-name rows and will show an empty name. Re-process them if needed. No backfill.

## Task 3: Multilingual, handwriting-aware prompt

In [extract.py](backend/pipeline/stages/extract.py):

**SYSTEM**: forms may mix printed and handwritten text, in Hebrew, English, Arabic or Russian (or another language).
- Copy names in their original script. No translation or transliteration.
- When something is written but unclear, return the best reading with `legible=false` and a low confidence.
- Return null only when there is nothing written, it is crossed out or cut off, or it cannot be read at all.
- Never invent or infer values from other fields.

**Tool schema**: add to each field:
- `handwritten: boolean`
- `script`: enum `hebrew|latin|arabic|cyrillic|digits|mixed`. Used only for logs and eval; field values are never logged.

**PROMPT**: return `box` for the place where the value is written even if the value is null, so it can be re-read from a crop.

**Other changes**
- `parse_field`: read `handwritten`, and keep `box` even when `value` is None.
- [base.py](backend/pipeline/base.py) `FieldResult`: add `handwritten: bool = False`.
- Update the module docstring: no more "unclear values must come back as null".

## Task 4: Re-read from a zoomed crop

**New file `backend/pipeline/crops.py`**
- `crop_b64(image_path, box, margin=0.03, min_width=1000) -> str`: crop from the full-resolution page image (200 DPI, not the shrunk one).
  - Widen the box by the margin, upscale with LANCZOS until it is at least `min_width` wide, and encode as PNG.
  - If there is no box, fall back to `None`. The caller then sends top and bottom halves of the page at full resolution.

**Changes in [confidence.py](backend/pipeline/stages/confidence.py)**

`base_level`: `handwritten=True` adds the soft reason `handwritten`, so a handwritten field is never `ok` after a single read.

Double-check candidates:
- (a) `review` fields with only soft reasons, as today.
- (b) **New:** `empty` fields among `full_name` and `id_number`.

Each candidate field is re-read from its own crop, with one call per field (or one call per half-page when there's no box). Use `asyncio.gather`, limited by the existing concurrency.

`DOUBLE_CHECK_PROMPT` is updated to say: "This is a zoomed crop of one field … may be handwritten in Hebrew/English/Arabic/Russian".

Result rules:
- **Field that had a value:** the reads agree (`values_equal`) → `ok` plus `double_check_confirmed`. They disagree → stays `review`. This is the current rule; only the input is now a crop.
- **Field that was empty and got a value from the crop:** the value is stored with the soft reason `recovered_on_zoom` and level **`review`**. Never `ok`, because there was only one read.

## Task 5: Normalization and validation

**[normalizers.py](backend/pipeline/normalizers.py)**
- `normalize_id`: digits only and `lstrip("0")`, with no `zfill`. For example 011223344 becomes 11223344.
- `normalize_name` for `full_name`:
  - Unicode NFC, then collapse whitespace.
  - Strip edge punctuation, but **keep** a trailing `'`/`׳` (ג'ורג') and inner hyphens.
- `values_equal` on strings: compare after NFC and `casefold()`, so case differences in Latin/Cyrillic don't count as disagreement.

**[israeli_id.py](backend/validators/israeli_id.py)**
- `is_valid_id` accepts 5-9 digits and pads to 9 internally before computing the check digit.

## Task 6: Tests and evaluation

**Update existing tests**
- `test_normalize`, `test_export`, `test_pipeline_failure`, `test_claude_client`: switch to `full_name`, and expect IDs without padding.

**New tests**
- `normalize_id("011223344") == "11223344"`.
- `is_valid_id("11223344")` is True.
- Names: Arabic, Cyrillic, ג'ורג', NFC.
- A handwritten field with high confidence → `review`.
- An empty `full_name` recovered from a crop → `review` plus `recovered_on_zoom`, never `ok`.
- A crop agreement on a handwritten field → `ok`.
- `crop_b64` with a box and without one.

**Evaluation**
- [eval/run.py](eval/run.py): a ground-truth cell holding `*` means not scored. Skip it in `load_truth` and `evaluate`. Also add a per-field "handwritten" breakdown in `report.md`.
- `eval/samples/gggg.pdf` plus rows in `ground_truth.csv`, using the new header (`full_name`):
  - Page 1: `ישראל ישראלי`, `11223344`, other fields `*`.
  - Page 2: the same name and ID; the rest `*`. ⚠ To be confirmed by you.

## Task 7: Docs and security fix

- [mission.md](agent-os/product/mission.md): "7 fields" becomes 6, with first and last name replaced by full name.
- [roadmap.md](agent-os/product/roadmap.md): add handwriting support.
- **Security:** remove the hard-coded API key default from [config.py:18](backend/app/config.py#L18). It is loaded from `.env` only, and the server fails clearly at startup if it's missing. Also recommend revoking the key on the Anthropic console.

---

## Files

**Modified**
- Backend: `app/fields.py`, `app/db.py`, `app/config.py`, `pipeline/base.py`, `pipeline/stages/extract.py`, `pipeline/stages/confidence.py`, `pipeline/normalizers.py`, `validators/israeli_id.py`, `tests/*`
- Frontend: `lib/api.ts`, `lib/labels.ts`, `pages/ReviewPage.tsx`, `pages/ExportPage.tsx`
- Config and eval: `config/export.yaml`, `eval/run.py`, `eval/ground_truth.csv`

**New**
- `backend/pipeline/crops.py`
- `eval/samples/gggg.pdf`

## Verification

1. `cd backend && .venv/Scripts/python -m pytest`: all tests pass, including the new ones.
2. `backend/.venv/Scripts/python -m eval.run` on `gggg.pdf`, which makes a real Claude call. In `eval/report.md`:
   - `full_name` = "ישראל ישראלי" and `id_number` = "11223344", at level `review` or `ok` (after agreement), never `empty`.
   - Hidden errors = 0.
3. In the app (`docker compose up`, :8080):
   1. Upload `gggg.pdf`.
   2. On the review screen, the full name and ID appear marked orange next to the image, and Enter confirms them.
   3. The exported Excel has a "שם מלא" column, and the ID has no leading zero.
4. `cd frontend && npm run build`: no TypeScript errors after the field change.
