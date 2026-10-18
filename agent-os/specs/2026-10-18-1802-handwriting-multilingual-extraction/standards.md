# Standards for Handwriting Support

There is no `agent-os/standards/` folder in the project yet, so no formal standard applies. Run `/discover-standards` to create one.

These constraints carry over from the Phase 1 spec (`2026-10-15-2332-phase1-mvp-form-extraction`):

- **Data sent out:** only page images (or crops of them) go to Claude. Nothing else leaves the machine.
- **Logs:** they never contain field values.
- **Python compatibility:** code stays Python 3.9-compatible (Docker uses 3.12).
- **Stage protocol:** stages follow the Stage protocol in `pipeline/base.py`. Config lives outside the code, in YAML seeded into the DB.
- **Validation failures:** they always stay `review`. The double-check may upgrade only fields whose reasons are all soft.
