"""Stage 7 — validate: ID check digit, real non-future date, sender from the closed list, and the lab's own rules."""
import json

from app.logging_utils import get_logger, log_event
from pipeline.base import Context, FormDoc
from validators.dates import check_date
from validators.israeli_id import is_valid_id
from validators.rules import evaluate
from validators.senders import is_canonical

log = get_logger("validate")


def apply_rules(form: FormDoc, ctx: Context) -> None:
    """Active rules written by the lab manager: a broken rule flags its field (`rule:<id>`), never changes it."""
    values = {n: fr.value for n, fr in form.fields.items()}
    for rule in ctx.rules or []:
        try:
            spec = json.loads(rule.spec) if isinstance(rule.spec, str) else rule.spec
            target = spec["then"]["field"]
            if target in form.fields and evaluate(spec, values, ctx.senders_cfg):
                form.fields[target].add_reason("validation", f"rule:{rule.id}")
        except Exception as e:  # a bad rule never fails a form
            log_event(log, "rule_failed", rule_id=getattr(rule, "id", None), error=type(e).__name__)


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
        apply_rules(form, ctx)
        return form
