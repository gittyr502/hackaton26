# References for Edge Cases and Robustness

## Similar Implementations

### Orientation check: a cheap Claude call that never blocks the form
- **Location:** `backend/pipeline/stages/classify.py`
- **Relevance:** classification (document type, blank page, continuation page, regions) is added to this same call.
- **Key patterns:** thumbnail, forced tool, and a `try/except` that falls back to the default.

### Pause, resume and cancel
- **Location:** `backend/pipeline/control.py`, `backend/app/api/batches.py` (pause/resume/cancel)
- **Relevance:** the batch is paused automatically when the API is unavailable.

### Retrying a single form
- **Location:** `backend/pipeline/runner.py` (`retry_form`, `run_docs` and its fan-out)
- **Relevance:** overriding a page's classification, retrying all failed forms, and splitting into regions through the existing fan-out.

### Recovery after a restart
- **Location:** `backend/app/main.py` (`recover_interrupted`)
- **Relevance:** gets an `interrupted` code and a finish time.

### Review screen with polling
- **Location:** `frontend/src/pages/ReviewPage.tsx`, `frontend/src/hooks/usePolling.ts`
- **Relevance:** reviewing while processing is still running. Needs protection so polling doesn't overwrite a field while it is being edited.

### Tests with a stub client
- **Location:** `backend/tests/test_pipeline_failure.py`, `backend/tests/conftest.py`
- **Relevance:** the pattern for the new edge-case tests.
