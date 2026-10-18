# טופסי התחייבות: Commitment forms to Excel

Turns a stack of lab commitment forms (scanned PDFs, phone photos, handwriting) into an RTL Excel sheet with one row per commitment and 7 fields. Every field gets a confidence level (ok / review / empty). A review screen shows the form image beside the table, so the fields that need checking can be confirmed or fixed quickly.

Product docs live in `agent-os/product/`. The build spec is in `agent-os/specs/2026-10-15-2332-phase1-mvp-form-extraction/`.

## Run

```bash
cp .env.example .env        # then set ANTHROPIC_API_KEY
docker compose up --build
```

Open **http://localhost:8080**.

Everything runs locally. The only external call is the Claude API, and it receives only the page image. Uploaded files and the SQLite DB live in `./data/`, which git ignores.

## Use

1. **Upload:** drop one file or many (PDF, JPG, PNG, HEIC). Each file shows a progress bar, and the app moves to review when processing finishes.
2. **Review:** fields waiting for review are orange. Hover a field to see why it was flagged.
   - **Enter** confirms the field, or saves your edit, and jumps to the next orange field. **Esc** cancels.
   - Pressing Enter outside a field starts from the first orange field.
   - Edits are saved to the server immediately.
   - "רק לבדיקה" (review only) filters the table to forms that still need review.
   - Use the zoom and rotate buttons on the image as needed.
   - A failed form has a "נסה שוב" (Try again) button.
3. **Export:** downloads the xlsx. You get a warning if orange fields remain. Batch delete removes the files and all records.

## Configuration (no code changes needed)

| File | What |
|---|---|
| `config/pipeline.yaml` | stage order, concurrency, retries, confidence threshold, double-check on/off |
| `config/senders.yaml` | closed list of senders with aliases, and the fuzzy-match threshold |
| `config/export.yaml` | Excel columns (order and Hebrew headers), date format, separator |
| `.env` | `ANTHROPIC_API_KEY`, `CLAUDE_MODEL` (default `claude-sonnet-5-5`) |

### How confidence works

A field's level is its **weakest signal**: model confidence below the threshold, illegibility, or a failed validation (ID check digit, invalid or future date, sender not in the list). A value the model couldn't read is left **empty**, never guessed.

With `double_check.enabled`, fields flagged only by soft signals (low confidence or illegible) get a second, focused read. If both reads agree, the field becomes ok. Validation failures always stay orange.

## Pipeline

`ingest → preprocess → split → classify → extract → normalize → validate → confidence`

Each stage has its own file in `backend/pipeline/stages/` and implements `run(form, ctx)`. To add a capability, write a stage class and add a line to `config/pipeline.yaml`.

## Tests and accuracy

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt   # Linux/mac: .venv/bin/pip
.venv/Scripts/python -m pytest
```

Accuracy eval: put 10–15 forms in `eval/samples/`, and their correct values in `eval/ground_truth.csv`. Use one row per page and separate multiple values with `;`. Then run:

```bash
backend/.venv/Scripts/python -m eval.run          # from the repo root
# or inside Docker:
docker compose exec -w /app backend python -m eval.run
```

The report (`eval/report.md`) lists per-field accuracy, **hidden errors** (marked ok but wrong; the target is 0), flag rate, and false empties.

## Networks that intercept HTTPS (NetFree, antivirus, corporate proxy)

If installs or Claude calls fail with `CERTIFICATE_VERIFY_FAILED` or `APIConnectionError`:

- **Claude API at runtime:** put the filter's root certificate at `certs/ca.crt` and add `SSL_CERT_FILE=/certs/ca.crt` to `.env`. For local runs outside Docker, use the local path instead.
- **Docker builds:** add these to `.env`, then rebuild:
  ```
  PIP_EXTRA_ARGS=--trusted-host pypi.org --trusted-host files.pythonhosted.org
  NPM_EXTRA_ARGS=--strict-ssl=false
  ```

## Local development without Docker

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
cd frontend && npm install && npm run dev      # http://localhost:5173, proxies /api to :8000
```
