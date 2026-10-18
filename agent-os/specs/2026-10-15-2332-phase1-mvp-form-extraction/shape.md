# Phase 1 MVP: Commitment-Form Extraction — Shaping Notes

## Scope

The full Phase 1 MVP from `agent-os/product/roadmap.md`:
- upload of one file or a stack (PDF, JPG, PNG, HEIC) with per-file progress
- an 8-stage pipeline (ingest → preprocess → split → classify → extract → normalize → validate → confidence)
- a review-and-fix screen
- RTL Excel export
- batch delete
- an accuracy eval script
- pytest
- `docker compose up`

## Decisions

- Build backend first, then the UI. Each layer is testable before the next.
- No visuals or sample forms yet. The UI is designed from the roadmap description.
- Excel format: no fixed lab format is known. Default Hebrew columns in field order, defined in `config/export.yaml` so they can change without code changes.
- Extraction model: `claude-sonnet-5-5` by default, overridable with `CLAUDE_MODEL` in `.env`.
- Double-check (togglable): a second focused Claude read runs on non-ok fields. It upgrades a field to ok **only** when both reads agree and the only weak signals were soft (model confidence or legibility). Validation failures (ID check digit, future date, sender not in list) always stay review.
- Pipeline stages may return a list of FormDocs, so `split` can fan out pages while keeping the `Stage(Protocol)` contract.
- A failed form never stops the batch. Retry re-runs it from `classify` onward.

## Context

- **Visuals:** None
- **References:** None. The repo was empty apart from the product docs.
- **Product alignment:** Full alignment with mission.md, roadmap.md and tech-stack.md: single user with no auth; "empty beats a guess"; Enter-to-approve review; modular stages wired through pipeline.yaml; only page images are sent to Claude; logs hold no field values; target is 30 forms in about 4 minutes.

## Standards Applied

None yet. There is no `agent-os/standards/` folder. Run `/discover-standards` once the code exists.

## Implementation Notes (added during build)

- The UI is served on **http://localhost:8080**, not :80, to avoid clashing with services that commonly hold port 80 on Windows.
- shadcn/ui components (Button, Dialog, Tooltip, Progress) were written by hand on top of Radix, the same way the shadcn CLI copies them into a project, so no interactive CLI was needed.
- The backend code is Python 3.9-compatible (`Optional`/`List` typing), so pytest runs on the dev machine's local 3.9. Docker uses 3.12.
- The dev network intercepts HTTPS, so pip, npm and the Claude API fail certificate checks. The README documents `SSL_CERT_FILE` and the `PIP_EXTRA_ARGS`/`NPM_EXTRA_ARGS` build args.
- `tool_choice` is `{"type": "auto"}`, not a forced tool, because some models reject `"tool"`/`"any"`. The system prompt requires answering only through the tool. A reply without the expected `tool_use` block raises `NoToolUseError`, and the existing backoff loop retries it.
