"""Stage 6 — normalize: clean values, ID to 9 digits, dates to ISO, split lists, map sender.

A reading that reviewers always corrected to the same value (see pipeline.learning) gets that value.
"""
from pipeline.base import Context, FormDoc
from pipeline.learning import lessons_of
from pipeline.normalizers import normalize_field


class Normalize:
    def run(self, form: FormDoc, ctx: Context) -> FormDoc:
        lessons = lessons_of(ctx)
        for name, fr in form.fields.items():
            learned = lessons.learned_value(name, fr.raw_value)
            if learned is not None:
                fr.value, fr.learned = learned, True
                continue
            fr.value, reasons = normalize_field(name, fr.value, ctx.senders_cfg)
            for r in reasons:
                fr.add_reason(r["kind"], r["code"])
        return form
