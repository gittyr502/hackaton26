"""Stage 6 — normalize: clean values, ID to 9 digits, dates to ISO, split lists, map sender."""
from pipeline.base import Context, FormDoc
from pipeline.normalizers import normalize_field


class Normalize:
    def run(self, form: FormDoc, ctx: Context) -> FormDoc:
        for name, fr in form.fields.items():
            fr.value, reasons = normalize_field(name, fr.value, ctx.senders_cfg)
            for r in reasons:
                fr.add_reason(r["kind"], r["code"])
        return form
