"""Stage 4 — classify: every page is a commitment form in the MVP; the page is also turned upright.

Scans and photos often arrive sideways or upside down (and PDFs carry no EXIF), which makes both the
reading and the field frames unreliable. A cheap look at a small copy of the page tells how far to turn it;
the page image on disk is rotated so every later stage and the review viewer see the same upright page.

Phase 2 hook: detect the sender template and pick a dedicated prompt.
"""
import base64
import io

from PIL import Image

from app.logging_utils import get_logger, log_event
from pipeline.base import Context, FormDoc

log = get_logger("classify")

THUMB_EDGE = 900

SYSTEM = "You check the orientation of scanned forms. Text on a correctly oriented page reads left-to-right or right-to-left, top to bottom."

PROMPT = (
    "Look at the printed text of this scanned form. How many degrees must the image be rotated CLOCKWISE "
    "so that the text is upright and readable? Answer 0 if it is already upright, 90, 180 or 270. "
    "Use the printed headings and labels to decide, not the handwriting."
)

TOOL = {
    "name": "record_orientation",
    "description": "Record the clockwise rotation that makes the page upright.",
    "input_schema": {
        "type": "object",
        "properties": {"clockwise_degrees": {"type": "integer", "enum": [0, 90, 180, 270]}},
        "required": ["clockwise_degrees"],
    },
}


def _thumb_b64(path: str) -> str:
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((THUMB_EDGE, THUMB_EDGE))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def rotate_clockwise(path: str, degrees: int) -> None:
    """Rotate the image file in place, clockwise, keeping the full canvas."""
    with Image.open(path) as im:
        im.load()
        out = im.rotate(-degrees, expand=True)
    out.save(path, "PNG")


async def fix_orientation(form: FormDoc, ctx: Context) -> int:
    got = await ctx.client.call_tool(
        image_b64=_thumb_b64(form.image_path), media_type="image/jpeg",
        prompt=PROMPT, tool=TOOL, system=SYSTEM,
    )
    try:
        degrees = int(got.get("clockwise_degrees", 0)) % 360
    except (TypeError, ValueError):
        return 0
    if degrees not in (90, 180, 270):
        return 0
    rotate_clockwise(form.image_path, degrees)
    log_event(log, "page_rotated", form_id=form.form_id, degrees=degrees)
    return degrees


class Classify:
    async def run(self, form: FormDoc, ctx: Context) -> FormDoc:
        form.form_type = "commitment"
        if ctx.pipeline_cfg.get("orientation", {}).get("enabled", True) and form.image_path:
            try:
                await fix_orientation(form, ctx)
            except Exception as e:  # a failed check must never block the form; it is read as it came
                log_event(log, "orientation_check_failed", form_id=form.form_id, error=type(e).__name__)
        return form
