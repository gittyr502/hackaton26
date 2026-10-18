"""Stage 7 — validate: ID check digit, real non-future date, sender from the closed list."""
from pipeline.base import Context, FormDoc
from validators.dates import check_date
from validators.israeli_id import is_valid_id
from validators.senders import is_canonical


class Validate:
    def run(self, form: FormDoc, ctx: Context) -> FormDoc:
        f = form.fields
        if "id_number" in f and f["id_number"].value is not None:
            if not is_valid_id(f["id_number"].value):
                f["id_number"].add_reason("validation", "invalid_id_checksum")
        if "receipt_date" in f and f["receipt_date"].value is not None:
            code = check_date(f["receipt_date"].value)
            if code:
                f["receipt_date"].add_reason("validation", code)
        if "sender" in f and f["sender"].value is not None:
            if not is_canonical(f["sender"].value, ctx.senders_cfg):
                f["sender"].add_reason("validation", "sender_not_in_list")
        return form
