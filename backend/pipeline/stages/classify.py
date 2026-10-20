"""Stage 4 — classify: what is on the page, and turn it upright.

One cheap look at a small copy of the page answers everything at once:
- how far to turn it (scans and photos often arrive sideways or upside down; PDFs carry no EXIF). The page
  is shown four times, turned 0/90/180/270 degrees, as tiles A-D, and the model picks the upright tile.
  Asking for "degrees to rotate" instead was wrong in 1 of 3 pages (mostly 90 vs 270, i.e. the wrong
  direction); picking the upright tile was right on every page tried, on every model. The page image on
  disk is rotated so every later stage and the review viewer see the same upright page;
- a slight tilt (crooked scan or photo) is straightened locally (pipeline/deskew.py), so field frames line up;
- what it is: a commitment form, the continuation page of the form before it, another medical document,
  something unrelated, or a blank page. Only commitments (and continuations) are read;
- whether several commitments share the page (e.g. stickers photographed together): each one becomes
  its own form, read from a crop of its region;
- whether the photo is poor or the form is cut off, which sends the form to review.

Every answer is optional: a missing or invalid one means today's default (an upright single commitment),
and a failed check never blocks the form.

Phase 2 hook: detect the sender template and pick a dedicated prompt.
"""
import base64
import io
from pathlib import Path
from typing import List, Optional, Union

from PIL import Image, ImageDraw, ImageFont

from app.logging_utils import get_logger, log_event
from pipeline.base import Context, FormDoc
from pipeline.deskew import deskew

log = get_logger("classify")

THUMB_EDGE = 900
TILE_EDGE = 760  # each of the four orientation tiles; the 2x2 sheet stays under the API's 1568 px
TILES = {"A": 0, "B": 90, "C": 180, "D": 270}  # tile -> clockwise degrees that turn the page that way

DOC_TYPES = ["commitment", "continuation", "other_medical", "unrelated", "blank"]

SYSTEM = (
    "You check scanned pages before they are read. The lab receives commitment forms (טופס התחייבות) "
    "from health funds and hospitals: a form with patient name, ID number, sample / central numbers, "
    "receipt date, sender and commitment numbers. Text on a correctly oriented page reads left-to-right "
    "or right-to-left, top to bottom."
)

PROMPT = (
    "The same scanned page is shown four times, turned differently, in tiles A, B, C and D.\n"
    "1. upright_tile: the tile in which the page is upright, so its printed headings and labels read normally "
    "(not sideways, not upside down). Judge by the printed text, not the handwriting.\n"
    "Answer every other question about the page as it appears in that upright tile.\n"
    "2. doc_type: 'commitment' for a commitment form (or its first page); 'continuation' for a later page of a "
    "commitment that started on the previous page (no form header, e.g. 'page 2 of 2', more sample numbers); "
    "'other_medical' for another medical document (referral, lab results, letter); 'unrelated' for anything else; "
    "'blank' for an empty page (e.g. the back of a sheet).\n"
    "3. commitments_count: how many separate commitment forms are on this page (usually 1).\n"
    "4. regions: when there are 2 or more, one box per form as [x0, y0, x1, y1] fractions of the upright tile "
    "(measured from its top-left corner); "
    "otherwise an empty list.\n"
    "5. quality: 'poor' if the image is too blurry, dark or skewed to read reliably, else 'good'.\n"
    "6. cut_off: true if part of the form is missing from the image (cut off at an edge or torn)."
)

TOOL = {
    "name": "record_orientation",
    "description": "Record which tile shows the page upright, and what the page is.",
    "input_schema": {
        "type": "object",
        "properties": {
            "upright_tile": {"type": "string", "enum": list(TILES)},
            "doc_type": {"type": "string", "enum": DOC_TYPES},
            "commitments_count": {"type": "integer", "minimum": 0},
            "regions": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}},
            "quality": {"type": "string", "enum": ["good", "poor"]},
            "cut_off": {"type": "boolean"},
        },
        "required": ["upright_tile"],
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


def ink_ratio(path: str) -> float:
    """Share of clearly dark pixels on a small grayscale copy: ~0 on an empty sheet."""
    with Image.open(path) as im:
        g = im.convert("L")
        g.thumbnail((400, 400))
        hist = g.histogram()
    total = sum(hist) or 1
    return sum(hist[:160]) / total


def _tiles_b64(path: str, tile: int = TILE_EDGE) -> str:
    """The page four times, turned 0/90/180/270 degrees clockwise, as labelled tiles A-D on one JPEG."""
    pad = 34
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((tile, tile))
        sheet = Image.new("RGB", (2 * (tile + pad), 2 * (tile + pad)), "white")
        draw = ImageDraw.Draw(sheet)
        try:
            font = ImageFont.load_default(size=24)
        except TypeError:  # Pillow < 10.1
            font = ImageFont.load_default()
        for i, (label, cw) in enumerate(TILES.items()):
            x, y = (i % 2) * (tile + pad), (i // 2) * (tile + pad)
            sheet.paste(im.rotate(-cw, expand=True), (x + pad, y + pad))
            draw.rectangle([x, y, x + pad - 4, y + pad - 4], fill="black")
            draw.text((x + 8, y + 3), label, fill="white", font=font)
    buf = io.BytesIO()
    sheet.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def ask_page(form: FormDoc, ctx: Context) -> dict:
    return await ctx.call_tool(
        "classify", image_b64=_tiles_b64(form.image_path), media_type="image/jpeg",
        prompt=PROMPT, tool=TOOL, system=SYSTEM,
    )


def degrees_of(got: dict) -> int:
    """Clockwise degrees that make the page upright: from the picked tile (or a plain angle, older answers)."""
    tile = got.get("upright_tile")
    if isinstance(tile, str) and tile.strip().upper() in TILES:
        return TILES[tile.strip().upper()]
    try:
        return int(got.get("clockwise_degrees", 0)) % 360
    except (TypeError, ValueError):
        return 0


def straighten(form: FormDoc, ctx: Context) -> float:
    """Undo a slight tilt so field frames sit on the writing. Never fails the form."""
    cfg = ctx.pipeline_cfg.get("orientation", {})
    if not cfg.get("deskew", True):
        return 0.0
    try:
        angle = deskew(form.image_path, max_angle=float(cfg.get("max_skew_degrees", 45)))
    except Exception as e:
        log_event(log, "deskew_failed", form_id=form.form_id, error=type(e).__name__)
        return 0.0
    if angle:
        log_event(log, "page_deskewed", form_id=form.form_id, degrees=angle)
    return angle


def apply_orientation(form: FormDoc, got: dict) -> int:
    degrees = degrees_of(got)
    if degrees not in (90, 180, 270):
        return 0
    rotate_clockwise(form.image_path, degrees)
    log_event(log, "page_rotated", form_id=form.form_id, degrees=degrees)
    return degrees


async def fix_orientation(form: FormDoc, ctx: Context) -> int:
    return apply_orientation(form, await ask_page(form, ctx))


def _valid_box(b) -> Optional[List[float]]:
    try:
        x0, y0, x1, y1 = (min(1.0, max(0.0, float(v))) for v in b)
    except (TypeError, ValueError):
        return None
    if x1 - x0 < 0.05 or y1 - y0 < 0.05:
        return None
    return [x0, y0, x1, y1]


def _crop_to(path: str, box: List[float], out: Path, margin: float = 0.01) -> None:
    with Image.open(path) as im:
        im.load()
        w, h = im.size
        rect = (max(0, int((box[0] - margin) * w)), max(0, int((box[1] - margin) * h)),
                min(w, int((box[2] + margin) * w)), min(h, int((box[3] + margin) * h)))
        im.crop(rect).save(out, "PNG")


def split_regions(form: FormDoc, boxes: List[List[float]]) -> List[FormDoc]:
    """One form per commitment on the page, each with the crop of its own region as its page image."""
    page = Path(form.image_path)
    outs = []
    for i, box in enumerate(boxes):
        out = page.with_name(f"{page.stem}_r{i + 1}.png")
        _crop_to(form.image_path, box, out)
        doc = form.model_copy(deep=True, update={
            "image_path": str(out), "region_index": i, "region_box": box,
            "form_id": form.form_id if i == 0 else None,
        })
        doc.add_form_reason("multiple_commitments")
        outs.append(doc)
    log_event(log, "page_split_into_regions", form_id=form.form_id, regions=len(outs))
    return outs


def apply_classification(form: FormDoc, got: dict, ctx: Context) -> Union[FormDoc, List[FormDoc]]:
    cfg = ctx.pipeline_cfg.get("classify", {})
    if cfg.get("doc_types", True):
        doc_type = got.get("doc_type")
        if doc_type in DOC_TYPES:
            form.doc_type = doc_type
        # never skip a page with clear writing on it as "blank": the cheap local look is a safety net
        if form.doc_type == "blank" and ink_ratio(form.image_path) > cfg.get("blank_max_ink", 0.01):
            form.doc_type = "commitment"
            form.add_form_reason("blank_uncertain")
    if got.get("quality") == "poor":
        form.add_form_reason("poor_quality")
    if got.get("cut_off") is True:
        form.add_form_reason("partial_page")

    regions_cfg = ctx.pipeline_cfg.get("regions", {})
    if form.doc_type == "commitment" and regions_cfg.get("enabled", True) and form.region_index is None:
        try:
            count = int(got.get("commitments_count") or 1)
        except (TypeError, ValueError):
            count = 1
        boxes = [b for b in (_valid_box(r) for r in (got.get("regions") or [])) if b]
        if count >= 2 and len(boxes) >= 2:
            return split_regions(form, boxes[: regions_cfg.get("max_regions", 6)])
        if count >= 2:  # several forms, but no usable boxes: keep the page whole and ask a human
            form.add_form_reason("multiple_commitments")
    return form


class Classify:
    async def run(self, form: FormDoc, ctx: Context) -> Union[FormDoc, List[FormDoc]]:
        form.form_type = "commitment"
        if form.forced_type:  # the user said what this page is: trust them, and read it as it is
            form.doc_type = form.forced_type
            return form
        orientation = ctx.pipeline_cfg.get("orientation", {}).get("enabled", True)
        if not form.image_path:
            return form
        if not orientation and not ctx.pipeline_cfg.get("classify", {}).get("doc_types", True):
            return form
        try:
            got = await ask_page(form, ctx)
        except Exception as e:  # a failed check must never block the form; it is read as it came
            log_event(log, "orientation_check_failed", form_id=form.form_id, error=type(e).__name__)
            if orientation:
                straighten(form, ctx)
            return form
        if not isinstance(got, dict):
            return form
        if orientation:
            apply_orientation(form, got)
            straighten(form, ctx)
        try:
            return apply_classification(form, got, ctx)
        except Exception as e:
            log_event(log, "classify_failed", form_id=form.form_id, error=type(e).__name__)
            return form
