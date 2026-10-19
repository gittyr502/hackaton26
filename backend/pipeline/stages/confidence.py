"""Stage 8 — confidence: level = the weakest signal (model confidence, legibility, handwriting, validation).

Optional double-check: a second, zoomed-in read of each candidate field from a crop of the page.
- A field with a value is upgraded to ok only when both reads agree AND every weak signal was soft
  (confidence / legibility / handwriting / fuzzy sender). Validation failures always stay "review".
- An empty name or ID is re-read too; a value recovered this way is only ever "review" (one read).
"""
import asyncio
from typing import Any, Dict, List, Optional

from app.fields import LEVEL_EMPTY, LEVEL_OK, LEVEL_REVIEW
from app.logging_utils import get_logger, log_event
from pipeline.base import Context, FieldResult, FormDoc
from pipeline.crops import crop_b64, halves_b64
from pipeline.normalizers import normalize_field, values_equal
from pipeline.stages.extract import SYSTEM, build_tool, encode_page, parse_field
from pipeline.stages.validate import Validate

log = get_logger("confidence")

# Empty fields worth a zoomed re-read: the ones most often handwritten.
RECOVERABLE = ("full_name", "id_number")

DOUBLE_CHECK_PROMPT = (
    "Look again, very carefully, only at these fields of the commitment form: {fields}. "
    "The image may be a zoomed-in crop of the form. The value may be handwritten, possibly faint, "
    "in Hebrew, English, Arabic or Russian. Read each value character by character and copy it "
    "in its original script. Return null if you are not certain."
)


def base_level(fr, threshold: float) -> str:
    if fr.value is None:
        return LEVEL_EMPTY
    if fr.confidence < threshold:
        fr.add_reason("soft", "low_confidence")
    if not fr.legible:
        fr.add_reason("soft", "illegible")
    if fr.handwritten:
        fr.add_reason("soft", "handwritten")
    return LEVEL_REVIEW if fr.reasons else LEVEL_OK


async def _read(ctx: Context, image_b64: str, media_type: str, names: List[str]) -> Dict[str, Any]:
    return await ctx.client.call_tool(
        image_b64=image_b64, media_type=media_type,
        prompt=DOUBLE_CHECK_PROMPT.format(fields=", ".join(names)),
        tool=build_tool(names), system=SYSTEM,
    )


async def _reread(ctx: Context, form: FormDoc, name: str) -> Optional[FieldResult]:
    """Second read of one field: from its crop, else page halves (empty field) or the full page."""
    fr = form.fields[name]
    crop = crop_b64(form.image_path, fr.box or fr.hint_box)
    if crop:
        return parse_field((await _read(ctx, crop, "image/png", [name])).get(name))
    if fr.value is None:
        # No box to zoom into: read both halves at full resolution; keep a value only if they don't conflict.
        values = []
        for half in halves_b64(form.image_path):
            got = parse_field((await _read(ctx, half, "image/png", [name])).get(name))
            if got.value is not None:
                values.append(got)
        if not values or any(not values_equal(v.value, values[0].value) for v in values[1:]):
            return None
        return values[0]
    return parse_field((await _read(ctx, encode_page(form.image_path), "image/jpeg", [name])).get(name))


class Confidence:
    async def run(self, form: FormDoc, ctx: Context) -> FormDoc:
        threshold = float(ctx.pipeline_cfg.get("confidence", {}).get("threshold", 0.85))
        for fr in form.fields.values():
            fr.level = base_level(fr, threshold)

        if not ctx.pipeline_cfg.get("double_check", {}).get("enabled", False):
            return form
        # Only fields whose every reason is soft can be upgraded, so only those are worth re-reading.
        candidates = [
            n for n, fr in form.fields.items()
            if (fr.level == LEVEL_REVIEW and all(r["kind"] == "soft" for r in fr.reasons))
            or (fr.level == LEVEL_EMPTY and n in RECOVERABLE)
        ]
        if not candidates:
            return form

        results = await asyncio.gather(*(_reread(ctx, form, n) for n in candidates), return_exceptions=True)
        recovered = False
        for n, second in zip(candidates, results):
            fr = form.fields[n]
            if isinstance(second, Exception):
                log_event(log, "double_check_failed", form_id=form.form_id, field=n, error=type(second).__name__)
                if fr.value is not None:
                    fr.add_reason("double_check", "double_check_failed")
                continue
            second_value = None
            if second is not None:
                second_value, _ = normalize_field(n, second.value, ctx.senders_cfg)

            if fr.value is None:
                if second_value is None:
                    continue
                fr.value, fr.raw_value = second_value, second.value
                fr.confidence, fr.legible, fr.handwritten = second.confidence, second.legible, second.handwritten
                # second.box is relative to the crop, not the page: keep the page box from the first read.
                fr.add_reason("soft", "recovered_on_zoom")
                fr.level = LEVEL_REVIEW
                recovered = True
                log_event(log, "field_recovered_on_zoom", form_id=form.form_id, field=n)
            elif second_value is not None and values_equal(fr.value, second_value):
                fr.level = LEVEL_OK
                fr.add_reason("info", "double_check_confirmed")
            else:
                fr.add_reason("double_check", "double_check_disagree")

        if recovered:
            # A recovered ID must still pass the check digit; validation reasons keep it in review.
            Validate().run(form, ctx)
        return form
