# References for Speed, Users, Patients, NL Rules

## Similar Implementations

### Pipeline execution and the Claude client
- **Location:** `backend/pipeline/claude_client.py`, `backend/pipeline/runner.py`, `backend/pipeline/stages/{classify,extract,localize,confidence}.py`, `backend/pipeline/crops.py`
- **Relevance:** these are where the per-page calls are made, along with the concurrency limit and the save points.
- **Key patterns:**
  - Fan-out with `asyncio.gather` in `run_docs`.
  - `_load_lessons`, which never fails a batch (the same pattern is used to load active rules).
  - Stub clients in the tests are duck-typed.

### Live review
- **Location:** `frontend/src/hooks/usePolling.ts`, `frontend/src/pages/ProcessingPage.tsx`, `frontend/src/pages/ReviewPage.tsx`
- **Key patterns:**
  - Stale-response guard and `localEdit`.
  - An `editing` ref so a poll does not overwrite the field being edited.
  - `goToNext`, which moves to the next field.
  - Version conflicts answered with 409.

### Analysis over existing data
- **Location:** `backend/pipeline/learning.py`, `backend/app/api/learning.py`, `backend/pipeline/duplicates.py`
- **Relevance:** a manager-only analysis endpoint, and queries by field value. These are the model for the rule dry run and the patient grouping.

### Validation
- **Location:** `backend/pipeline/stages/validate.py`, `backend/validators/senders.py`, `backend/pipeline/normalizers.py`
- **Key patterns:**
  - `add_reason("validation", code)`.
  - Matching against canonical sender names.
  - `values_equal`.

### Authentication and audit
- **Location:** `backend/app/auth.py`, `backend/app/audit.py`, `backend/app/db.py`
- **Key patterns:**
  - `require_roles` and `get_current_user` (which accepts `?token=`).
  - `_add_missing_columns` and `seed_users`.

### UI
- **Location:** `frontend/src/pages/DashboardPage.tsx`, `frontend/src/pages/IntakeQueuePage.tsx` (`formLink`), `frontend/src/components/ui/ConfirmDialog`, `frontend/src/i18n/locales/edge.ts`

## Visuals (Stitch)

- **Project:** `4499292770114359296`
- **Design system:** `assets/8849c62b3fe84eddbf07204131ae994f`
- **Screens:** see the list below, which Task 2 fills in.

| Screen | Stitch screen ID | Local file |
|---|---|---|
| Live review while processing | `2c465202015d4c3584d19d6c1dc70c72` | `visuals/live-review.html` |
| User management | `ae66d7345cd8490fa26fc24db7a5927e` | `visuals/users.html` |
| Validation rules | `8dd9cfb8bcb946c5b32c0521ba7387cf` | `visuals/rules.html` |
| Patient file | `322a221a07294b8eb212e79e00449bd7` (also `3beb89091d1d478da8ba02eff7a80c62`) | `visuals/patient-file.html` |

The screenshots could not be saved: the content filter on this network replaces downloaded images with a placeholder. Each screen is saved as its HTML file instead (Tailwind, RTL); open it in a browser to view it.
