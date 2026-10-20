# Standards for Speed, Users, Patients, NL Rules

There is still no `agent-os/standards/` folder. These constraints carry over from earlier specs:

- **Python version:** stay compatible with 3.9. Write `Optional[...]`, not `X | None`.
- **Configuration:** settings live in YAML (`pipeline.yaml`). New behavior comes with defaults that don't break existing tests.
- **Database columns:** every new column is added through `_add_missing_columns` (`backend/app/db.py`).
- **Audit:** every change to a workflow, field, user, rule or patient link calls `audit.record` in the same commit. Password hashes are never logged.
- **Permissions:** each route declares them with `Depends(require_roles(...))`. Role checks use `has_role`, never `user.role ==`.
- **Problems are codes:** use codes such as `last_admin`, `field_never_read` and `rule:<id>`. The UI translates them.
- **Logs:** never include field values.
- **What leaves the system:** only page images, crops, or the text of a rule are sent to Claude.
- **i18n:** Hebrew is the source, and every key exists in all four locales. Each feature gets its own locale file (the `edge.ts` pattern).
- **Test stubs:** existing stub clients keep working, and new arguments are passed only if the client accepts them.
