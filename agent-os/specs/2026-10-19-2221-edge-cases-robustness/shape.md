# Edge Cases and Robustness — Shaping Notes

## Scope

All of roadmap section 2ג.

The user raised seven cases:
1. Slow upload
2. Slow scanning
3. Empty file
4. Truncated or incomplete file
5. One commitment split across several pages
6. A document that is not a commitment
7. Correcting forms while the rest of the same upload is still being scanned

Eleven more were found in the code:
- several commitments on one page
- duplicates, by file hash and by commitment number
- password-protected PDF
- extension that doesn't match the content
- huge file
- poor-quality photo
- server restart mid-batch
- concurrent edits
- retry over manual corrections
- cancel mid-batch
- completely empty form

## Decisions

- **Nothing existing breaks.** Old endpoints stay, including the multi-file `POST /api/batches`. New columns go through `_add_missing_columns`, new behavior is configured in `pipeline.yaml`, and existing tests and stub clients pass unchanged.
- **Classification rides on the existing orientation call** (`record_orientation`). It gains optional properties, and a missing property means today's default: commitment, one region. This adds no time and no cost.
- **Blank pages** are detected locally by ink ratio, before any API call.
- **Pages that aren't commitments** (other medical, unrelated, blank) are not extracted. They are listed in a "not a commitment" group, and the user can override the classification.
- **Multi-page commitments** are merged automatically. A conflicting value becomes review with the reason `pages_disagree`. The user can split them again or merge with the previous page by hand.
- **Several commitments on one page** become one form per region, each extracted from a crop of its region and each marked for review.
- **Errors are codes** (`error_code`) and are translated in the UI. The old error text stays alongside the code.
- **Duplicates only warn.** Nothing is ever deleted automatically.
- **API unavailable** (key, quota, outage): the batch pauses with a single notice, and the user resumes once it is fixed.
- **Per-file upload:** each file is a separate request with stall detection and retry, and processing starts on each file as soon as it arrives.

## Context

- **Visuals:** None. The UI follows the existing design (DESIGN.MD, Stitch).
- **References:** see references.md.
- **Product alignment:** an empty field beats a guess (doubt means review); every new capability is a stage or setting in pipeline.yaml; only page images go to Claude; the UI is in 4 languages; the target is 30 forms in 4 minutes.

## Standards Applied

None defined (there is no `agent-os/standards/`). Constraints carried over from earlier specs:
- Python 3.9 compatibility.
- Logs contain no field values.
- Every mutation goes through `audit.record`.
- Permissions are declared with `require_roles`.
