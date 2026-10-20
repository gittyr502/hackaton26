# Speed, Users, Patients, NL Rules — Shaping Notes

## Scope

Roadmap §2ד, all four parts:

1. **Faster processing.** All pages are read in parallel, and a page can be reviewed while later pages are still being read.
2. **User management (CRUD)** with roles. There is a new `admin` role, and a user can have more than one role.
3. **Patient file.** Every commitment and referral is grouped by ID number.
4. **Validation rules in free Hebrew.** The rule is converted with Claude and run on existing data first ("the rule would have flagged 23 forms").

## Decisions

### Speed
- All speed levers are approved:
  - a model per stage, with Haiku for classify, localize and document;
  - adaptive concurrency starting at 16;
  - prompt caching;
  - JPEG crops;
  - the page halves read in parallel.
- Every switch to a faster model is checked against `eval.run` before it is kept.
- **Early save.** A form is saved and shown right after Validate, with provisional levels. Localize and the double check finish in the background and update only fields the user has not touched.
- **SSE plus cheaper polling.** Changes are pushed over SSE, and the poll no longer loads image blobs.

### Users
- `admin` does not inherit `lab_manager` permissions.
- Delete is soft.
- The last admin cannot be deactivated or lose the admin role.
- A `token_version` field invalidates old tokens.

### Patients
- A patient is identified by the normalized ID number (9 digits, zero-padded).
- If the ID is valid and was read confidently, the form is linked automatically. Otherwise the link is only suggested.
- A manual link or rejection is never overwritten.
- Referral pages (`other_medical`) get a light read on Haiku: ID, name, date, document type, test type and referral number.

### Rules
- New extracted fields: `test_type` and `referral_number`. They are optional, an empty value never holds a form back, and they are not in the export.
- Rules run on a deterministic engine. Claude is used only to convert the text into a rule.
- The Hebrew explanation is generated from the rule spec itself, so it always matches what will actually run.
- An unknown term is never guessed. The system asks the manager what was meant.
- When a rule is turned on it can also flag forms that are still open. Approved forms are never touched.

## Context

- **Visuals:** 4 Stitch screens in the project "MediScan RTL Excel Converter". They are saved to `visuals/` if the generation succeeds.
- **References:** see `references.md`.
- **Product alignment:** roadmap §2ד, and the existing constraints in `tech-stack.md`.

## Standards Applied

No `agent-os/standards/` folder exists. The constraints carried over from earlier specs are listed in `standards.md`.

## Results (execution)

**Speed:** the 6-page sample PDF.
- First page ready after 15.6 s; the whole file done in 52.6 s.
- Earlier runs of the same file took 38–437 s.
- What slowed it down: with `tool_choice: auto`, Haiku sometimes answered in text. Each of those replies was retried with backoff, and calls took about 8 s.
- The fix: the tool is now forced wherever the model allows it. Haiku then takes about 2 s per call and always calls the tool.
- Opus rejects a forced tool. The client falls back to `auto` for it and remembers that for the model.

**Rules:** with real Claude, the example rule converted in 3.3 s to exactly the intended spec. On a copy of the real DB, the dry run checked 136 forms, flagged 10, and correctly warned `field_never_read` for `referral_number`.

**Eval:** 0 hidden errors. The ground truth has only 1 form (2 scored fields), so this is weak evidence. Expand `eval/ground_truth.csv` before relying on Haiku for classify and localize.

**Visuals:** saved as HTML. The local content filter replaces downloaded images with a placeholder.
