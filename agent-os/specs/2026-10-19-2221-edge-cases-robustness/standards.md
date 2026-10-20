# Standards for Edge Cases and Robustness

There is no `agent-os/standards/` folder in the project yet. Run `/discover-standards` to create one.

Constraints carried over from earlier specs:

- **Data sent out:** only page images, or crops of them, are sent to Claude.
- **Logs:** they never contain field values.
- **Python compatibility:** code stays compatible with Python 3.9. Use `Optional[...]`, not `X | None`.
- **Config:** it lives outside the code, in YAML.
- **Validation failures:** they always stay `review`.
- **Audit:** every workflow transition and every field change calls `audit.record(...)`, in the same commit as the change.
- **Permissions:** declared per route with `Depends(require_roles(...))`. Ownership is checked in the shared helpers.
- **DB schema:** a new column goes in `_add_missing_columns` (`backend/app/db.py`).
- **i18n:** Hebrew is the source. Every key must exist in all four locales (the compiler checks).

New in this spec:

- **Problems are codes.** A problem with a file or a form is stored as a stable code (`error_code`, `warnings`, `reasons`), and the UI translates it. The free text stays alongside the code for compatibility.
- **Failures stay local.** An edge case fails only its own file or form, never the whole batch.
