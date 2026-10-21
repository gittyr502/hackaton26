"""Stage 8 — confidence: level = the weakest signal (model confidence, legibility, handwriting, validation).

Optional double-check: a second, zoomed-in read of each candidate field from a crop of the page.
- A field with a value is upgraded to ok only when both reads agree AND every weak signal was soft
  (confidence / legibility / handwriting / fuzzy sender). Validation failures always stay "review".
- An empty name or ID is re-read too; a value recovered this way is only ever "review" (one read).
"""
import asyncio
from typing import Any, Dict, List, Optional, Tuple

from app.fields import LEVEL_EMPTY, LEVEL_OK, LEVEL_REVIEW
from app.logging_utils import get_logger, log_event
from pipeline.base import Context, FieldResult, FormDoc
from pipeline.crops import MEDIA_TYPE, crop_b64, halves_b64
from pipeline.learning import lessons_of
from pipeline.normalizers import normalize_field, values_equal
from pipeline.stages.extract import SYSTEM, build_tool, encode_page, parse_field
from pipeline.stages.validate import Validate

log = get_logger("confidence")

# A field read with at least this confidence needs no human look on that account (other weak signals still do).
DEFAULT_THRESHOLD = 0.65
# Handwriting is read less reliably: it needs more confidence than print to skip the clerk.
DEFAULT_HANDWRITING_THRESHOLD = 0.80

# Empty fields worth a zoomed re-read: the ones most often handwritten.
RECOVERABLE = ("full_name", "id_number")

DOUBLE_CHECK_PROMPT = (
    "Look again, very carefully, only at these fields of the commitment form: {fields}. "
    "The image may be a zoomed-in crop of the form. The value may be handwritten, possibly faint, "
    "in Hebrew, English, Arabic or Russian. Read each value character by character and copy it "
    "in its original script. Return null if you are not certain."
)


def thresholds(pipeline_cfg: Dict[str, Any]) -> Tuple[float, float]:
    """(confidence threshold, handwriting threshold) from the pipeline config."""
    cfg = pipeline_cfg.get("confidence") or {}
    return (float(cfg.get("threshold", DEFAULT_THRESHOLD)),
            float(cfg.get("handwriting_threshold", DEFAULT_HANDWRITING_THRESHOLD)))


def base_level(fr, threshold: float, handwriting_threshold: float = DEFAULT_HANDWRITING_THRESHOLD) -> str:
    if fr.value is None:
        # empty, unless a rule says it must not be (e.g. a required referral number)
        return LEVEL_REVIEW if any(r["kind"] == "validation" for r in fr.reasons) else LEVEL_EMPTY
    if fr.confidence < threshold:
        fr.add_reason("soft", "low_confidence")
    if not fr.legible:
        fr.add_reason("soft", "illegible")
    if fr.handwritten and fr.confidence < max(threshold, handwriting_threshold):
        fr.add_reason("soft", "handwritten")
    return LEVEL_REVIEW if fr.reasons else LEVEL_OK


async def _read(ctx: Context, image_b64: str, media_type: str, names: List[str]) -> Dict[str, Any]:
    return await ctx.call_tool(
        "double_check", image_b64=image_b64, media_type=media_type,
        prompt=DOUBLE_CHECK_PROMPT.format(fields=", ".join(names)) + lessons_of(ctx).prompt_for(names),
        tool=build_tool(names), system=SYSTEM,
    )


async def _reread(ctx: Context, form: FormDoc, name: str) -> Optional[FieldResult]:
    """Second read of one field: from its crop, else page halves (empty field) or the full page."""
    fr = form.fields[name]
    crop = crop_b64(form.image_path, fr.box or fr.hint_box)
    if crop:
        return parse_field((await _read(ctx, crop, MEDIA_TYPE, [name])).get(name))
    if fr.value is None:
        # No box to zoom into: read both halves (in parallel); keep a value only if they don't conflict.
        reads = await asyncio.gather(*(_read(ctx, half, MEDIA_TYPE, [name]) for half in halves_b64(form.image_path)))
        values = [got for got in (parse_field(r.get(name)) for r in reads) if got.value is not None]
        if not values or any(not values_equal(v.value, values[0].value) for v in values[1:]):
            return None
        return values[0]
    return parse_field((await _read(ctx, encode_page(form.image_path), "image/jpeg", [name])).get(name))


def apply_lessons(form: FormDoc, ctx: Context) -> None:
    """Show where a value came from a lesson, and never let a field reviewers keep catching pass unseen."""
    risky = lessons_of(ctx).risky
    for n, fr in form.fields.items():
        if fr.learned:
            fr.add_reason("info", "learned_correction")
        if fr.level == LEVEL_OK and n in risky:
            fr.add_reason("soft", "often_corrected")
            fr.level = LEVEL_REVIEW
            log_event(log, "field_held_for_review", form_id=form.form_id, field=n, rate=risky[n])


class Confidence:
    async def run(self, form: FormDoc, ctx: Context) -> FormDoc:
        form = await self._assess(form, ctx)
        apply_lessons(form, ctx)
        return form

    async def _assess(self, form: FormDoc, ctx: Context) -> FormDoc:
        threshold, handwriting = thresholds(ctx.pipeline_cfg)
        for fr in form.fields.values():
            fr.level = base_level(fr, threshold, handwriting)

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
