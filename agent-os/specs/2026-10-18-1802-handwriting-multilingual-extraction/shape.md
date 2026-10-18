# Handwriting Support (multilingual) — Shaping Notes

## Scope

Extract handwritten fields from commitment forms, especially the patient's name and ID. Handwriting may be in Hebrew, English, Arabic or Russian. Today a handwritten name or ID comes back empty, so the technician has to type it by hand.

The scope also includes two output changes the user asked for:
- **One full-name field:** `full_name` replaces `first_name` and `last_name`.
- **ID without a leading zero:** "11223344", not "011223344".

## Root causes found

There is no OCR step and no PDF text layer; only the page image goes to Claude. Handwriting fails because of:
1. **The SYSTEM prompt:** "not sure of every character, return null", and it mentions only Hebrew.
2. **Downscaling:** the full page is shrunk to a 1568px long edge, about 134 DPI. Faint pen writing is lost.
3. **The double-check:** it never re-reads `empty` fields, and it re-reads from the same downscaled page.

## Decisions

- **Value plus review.** A handwritten or unclear value is returned as the best reading and marked `review`. A single read of handwriting is never `ok`.
- **Upgrading to ok.** A handwritten field becomes `ok` only when a second read from a zoomed crop agrees with the first.
- **Fields recovered from a crop.** An empty name or ID that comes back with a value from the crop is `review` (`recovered_on_zoom`).
- **Names stay in their original script.** No translation or transliteration.
- **ID validation.** The check-digit validation pads to 9 digits internally. The output has no leading zeros.
- **Old batches** in the DB are not migrated. Re-process them if needed.
- **Security.** The hard-coded API key default is removed from config.py.

## Context

- **Visuals:** `visuals/gggg.pdf`. This is a Meuhedet commitment form. The name and ID are handwritten in faint blue pen over the printed fields, and page 2 has handwriting at the top and a central number written on the left side.
- **Ground truth:** full name "ישראל ישראלי", ID "11223344".
- **References:** see references.md.
- **Product alignment:** the mission says "an empty field beats a guess" and "zero hidden errors". These are kept, because uncertain handwriting is always review and never ok without agreement. The mission was updated with handwriting support in four languages.

## Standards Applied

None. `agent-os/standards/` doesn't exist yet. See standards.md.
