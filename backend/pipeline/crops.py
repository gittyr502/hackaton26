"""Zoomed crops of the full-resolution page image, for re-reading handwritten or faint fields.

The extract stage sends a downscaled full page; small pen writing loses detail there.
Crops are cut from the original page render (preprocess DPI) and upscaled.
"""
import base64
import io
from typing import List, Optional, Sequence

from PIL import Image

MAX_UPSCALE = 4.0


def _encode_png(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def crop_b64(image_path: str, box: Optional[Sequence[float]], margin: float = 0.03,
             min_width: int = 1000) -> Optional[str]:
    """PNG (base64) of the normalized [x0, y0, x1, y1] box widened by `margin`, or None without a box."""
    if not box or len(box) != 4:
        return None
    x0, y0, x1, y1 = box
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        left = max(0, int((x0 - margin) * w))
        top = max(0, int((y0 - margin) * h))
        right = min(w, int((x1 + margin) * w))
        bottom = min(h, int((y1 + margin) * h))
        if right - left < 2 or bottom - top < 2:
            return None
        crop = im.crop((left, top, right, bottom))
    scale = min(MAX_UPSCALE, max(1.0, min_width / crop.width))
    if scale > 1.0:
        crop = crop.resize((round(crop.width * scale), round(crop.height * scale)), Image.LANCZOS)
    return _encode_png(crop)


def halves_b64(image_path: str, overlap: float = 0.05) -> List[str]:
    """Top and bottom halves of the page at full resolution (slightly overlapping), for fields without a box."""
    with Image.open(image_path) as im:
        im = im.convert("RGB")
        w, h = im.size
        mid = h // 2
        pad = int(h * overlap)
        parts = [im.crop((0, 0, w, min(h, mid + pad))), im.crop((0, max(0, mid - pad), w, h))]
    return [_encode_png(p) for p in parts]
