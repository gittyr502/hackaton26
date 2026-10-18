# Users, Roles, Approval Workflow and Dashboards — Shaping Notes

## Scope

The Phase 2א priority scope from the roadmap, due 28/10:
- Login, plus three roles: intake clerk, approver and lab manager.
- A `users` table, an `audit_log` table, and role-based permissions on every route.
- An approval workflow on each form, plus a personal area for each role.
- Four lab manager dashboards: backlog, auto-accuracy, problem fields and time to approval.

Out of scope: the system admin role and the external sender, which come only if time remains. Also SLA highlighting, saved filters and notifications.

## Decisions

- **Workflow is a separate column.** `Form.workflow` holds `needs_fix | pending_approval | returned | approved`. `Form.status` stays the pipeline state, so the existing `status == "done"` logic is untouched.
- **Starting state:** an all-`ok` form goes straight to `pending_approval`. A form with any `review` or `empty` field goes to `needs_fix` in the intake clerk's queue.
- **Return requires a comment.** The returned form goes back to its assignee.
- **Auth:** password (stdlib pbkdf2) plus a JWT (PyJWT, `JWT_SECRET` in `.env`). The Bearer token is kept in localStorage. Image URLs accept `?token=` because `<img>` can't send headers.
- **Visibility:**
  - An intake clerk sees their own uploads and forms assigned to them. The assignee defaults to the uploader.
  - An approver sees all `pending_approval` forms, read-only.
  - A lab manager sees everything and can reassign forms.
- **Export:** lab manager only, approved forms only. The Export page warns when a batch still has unapproved forms.
- **Audit:** every status change and field mutation goes through `audit.record`, in the same transaction. The dashboards derive from `audit_log`.
- **Demo users:** `intake1`, `approver1` and `manager1` are seeded with `DEMO_PASSWORD`.

## Context

- **Visuals:** none were provided. Four screens were generated in the Stitch project "MediScan RTL Excel Converter": login, intake queue, approver queue and manager dashboard. Their HTML exports are in `visuals/`. The PNG screenshots were blocked by the network filter (Netfree), so open the HTML files in a browser or view the screens in Stitch.
- **References:** see `references.md`.
- **Product alignment:**
  - The mission's single-user statement was true only for the MVP. This spec implements roadmap 2א.
  - `audit_log` stores before and after values in the DB. Those are data, not logs, so the rule "logs never contain field values" still holds.
- **Concurrent work:** another session is adding i18n to `frontend/src/main.tsx` and `src/i18n/*`. Edits there must stay small, and new strings go into the locale files.

## Standards Applied

There is no `agent-os/standards/` folder. The constraints carried over from earlier specs are listed in `standards.md`.

## Changes made while building

- **Export summary stats:** these still count every done form, so the Export page can show the review counts. Only the exported rows and the confidence sheet are filtered to approved forms. The summary adds `approved` and `unapproved` counts.
- **Extra demo user:** `intake2` was added so visibility and reassignment can be demoed.
- **Lab manager powers:** the lab manager can also submit, approve and return. These are supervisor overrides that are audited like any other transition.
- **Debug route:** `/debug/claude`, which spends API credits, is now lab-manager only.
- **Migration:** forms from before this change get `created_at` from their batch. Their workflow state is backfilled with the same rule as new forms.
