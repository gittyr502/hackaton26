"""Stage 5 — extract: read the 6 fields from the page image with Claude tool use.

Only the page image is sent. Values may be printed or handwritten, in any language.
Unclear but present values come back as a best reading flagged legible=false (-> review);
null is kept for values that are absent or cannot be read at all.
"""
import base64
import io
from typing import Any, Dict, Iterable, List, Optional

from PIL import Image

from app.fields import FIELD_NAMES, MULTI_FIELDS
from pipeline.base import Context, FieldResult, FormDoc

MAX_EDGE = 1568  # Claude's recommended long edge; keeps payloads small

FIELD_HINTS = {
    "full_name": "שם מלא של המטופל/ת (פרטי + משפחה) כפי שכתוב — מודפס או בכתב יד, בכל שפה",
    "id_number": "מספר תעודת זהות של המטופל/ת (ספרות בלבד) — מודפס או בכתב יד",
    "central_numbers": "מספרים מרכזיים (מספרי דגימה/מעבדה) — כל המספרים שמופיעים",
    "receipt_date": "תאריך קבלה, בדיוק כפי שכתוב בטופס",
    "sender": "הגורם השולח (קופת חולים / בית חולים / מרפאה)",
    "commitment_numbers": "מספרי התחייבות — כל המספרים שמופיעים",
}

SCRIPTS = ["hebrew", "latin", "arabic", "cyrillic", "digits", "mixed"]

SYSTEM = (
    "You transcribe lab commitment forms (טופס התחייבות) for a virology lab in Israel. "
    "Forms mix printed text and handwriting (pen, often faint or written over printed text). "
    "Handwriting may be in Hebrew, English, Arabic or Russian, or another language. "
    "Copy values exactly as written, in their original script: never translate or transliterate names. "
    "Accuracy matters more than completeness, and every value you return is shown to a human for checking: "
    "when something is written but hard to read, return your best reading with legible=false and a low confidence. "
    "Return null only when the value is absent, crossed out, cut off, or cannot be read at all. "
    "Never infer or invent values, and never copy a value from a different field."
)

PROMPT = (
    "Extract the fields from this commitment form using the record_form tool. "
    "Read handwritten values as carefully as printed ones; a handwritten value may override a printed placeholder. "
    "For each field give value (or null), confidence between 0 and 1 that the value is exactly right, "
    "legible=false if the handwriting or print is hard to read, handwritten=true if the value is handwritten, "
    "and script: the writing system of the value. "
    "central_numbers and commitment_numbers are lists: include every number you see for them. "
    "Also give box: the tight bounding box around the written value (not its printed label) as "
    "[x0, y0, x1, y1], fractions of the page width/height between 0 and 1, measured from the top-left corner. "
    "Give box even when value is null but something is written there, so it can be re-read zoomed in. "
    "For a list field, one box that covers all of its numbers."
)


def build_tool(fields: Iterable[str]) -> Dict[str, Any]:
    props = {}
    for name in fields:
        if name in MULTI_FIELDS:
            value_schema = {"type": ["array", "null"], "items": {"type": "string"}}
        else:
            value_schema = {"type": ["string", "null"]}
        props[name] = {
            "type": "object",
            "description": FIELD_HINTS[name],
            "properties": {
                "value": value_schema,
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "legible": {"type": "boolean"},
                "handwritten": {"type": "boolean"},
                "script": {"type": ["string", "null"], "enum": SCRIPTS + [None]},
                "box": {
                    "type": ["array", "null"],
                    "items": {"type": "number", "minimum": 0, "maximum": 1},
                    "minItems": 4,
                    "maxItems": 4,
                    "description": "[x0, y0, x1, y1] of the value on the page, as fractions from the top-left",
                },
            },
            "required": ["value", "confidence", "legible"],
        }
    return {
        "name": "record_form",
        "description": "Record the fields read from the form. Use null only for values that are absent or unreadable.",
        "input_schema": {"type": "object", "properties": props, "required": list(props)},
    }


def encode_page(image_path: str) -> str:
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        im.thumbnail((MAX_EDGE, MAX_EDGE))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def parse_box(raw: Any) -> Optional[List[float]]:
    """A usable normalized [x0, y0, x1, y1] box, or None. The model's coordinates are only a display aid."""
    if not isinstance(raw, (list, tuple)) or len(raw) != 4:
        return None
    try:
        x0, y0, x1, y1 = (min(max(float(v), 0.0), 1.0) for v in raw)
    except (TypeError, ValueError):
        return None
    if x1 - x0 < 0.005 or y1 - y0 < 0.003:
        return None
    return [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]


def parse_field(raw: Any) -> FieldResult:
    if not isinstance(raw, dict):
        return FieldResult(value=None, raw_value=None, confidence=0.0, legible=False)
    value = raw.get("value")
    if isinstance(value, str) and not value.strip():
        value = None
    if isinstance(value, list) and not value:
        value = None
    try:
        conf = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return FieldResult(value=value, raw_value=value, confidence=max(0.0, min(conf, 1.0)),
                       legible=bool(raw.get("legible", True)),
                       handwritten=bool(raw.get("handwritten", False)),
                       box=parse_box(raw.get("box")))


class Extract:
    async def run(self, form: FormDoc, ctx: Context) -> FormDoc:
        result = await ctx.client.call_tool(
            image_b64=encode_page(form.image_path), media_type="image/jpeg",
            prompt=PROMPT, tool=build_tool(FIELD_NAMES), system=SYSTEM,
        )
        form.fields = {name: parse_field(result.get(name)) for name in FIELD_NAMES}
        return form
