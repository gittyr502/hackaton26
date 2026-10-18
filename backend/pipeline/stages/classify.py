"""Stage 4 — classify: every page is a commitment form in the MVP.

Phase 2 hook: detect the sender template and pick a dedicated prompt.
"""
from pipeline.base import Context, FormDoc


class Classify:
    def run(self, form: FormDoc, ctx: Context) -> FormDoc:
        form.form_type = "commitment"
        return form
