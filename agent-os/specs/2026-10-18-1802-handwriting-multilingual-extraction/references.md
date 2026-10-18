# References for Handwriting Support

## Similar Implementations

### Extract stage
- **Location:** `backend/pipeline/stages/extract.py`
- **Relevance:** SYSTEM/PROMPT, tool schema (`build_tool`), `encode_page` downscaling, `parse_field`.
- **Key patterns:** each field is `{value, confidence, legible, box}`, and `box` is normalized [x0, y0, x1, y1]. The box is what the crops are built from.

### Confidence stage / double-check
- **Location:** `backend/pipeline/stages/confidence.py`
- **Relevance:** `base_level` decides the levels. The double-check re-reads candidates and upgrades them on agreement.
- **Key patterns:** reasons have a kind (`soft`/`validation`/`double_check`/`info`), and only soft-only fields can be upgraded.

### Normalizers / validators
- **Location:** `backend/pipeline/normalizers.py`, `backend/validators/israeli_id.py`, `backend/pipeline/stages/validate.py`
- **Relevance:** ID padding, name cleaning, and `values_equal` comparison.

### Evaluation
- **Location:** `eval/run.py`, `eval/ground_truth.csv`
- **Relevance:** measures accuracy, hidden errors and false empties per field.

### Phase 1 spec
- **Location:** `agent-os/specs/2026-10-15-2332-phase1-mvp-form-extraction/`
