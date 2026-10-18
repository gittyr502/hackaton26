"""Stage 3 — split: in the MVP every page is one form.

Phase 2 hook: smart splitting of long PDFs into multi-page forms.
"""
from typing import List

from pipeline.base import Context, FormDoc


class Split:
    def run(self, form: FormDoc, ctx: Context) -> List[FormDoc]:
        return [
            form.model_copy(update={"image_path": p, "page_index": i, "pages": []}, deep=True)
            for i, p in enumerate(form.pages)
        ]
