"""Straighten a slightly tilted page (a crooked scan or phone photo), locally, without any model call.

Lines of text make the row profile of a page "spiky" when they are horizontal: rows of ink alternate with
blank rows. Turned a few degrees, the lines smear across rows and the profile flattens. So we try small
angles and keep the one whose row profile varies the most (projection-profile deskew).
Only a pure-PIL implementation: a row profile is the page squeezed to one pixel wide (BOX filter = row mean).
"""
from typing import List, Tuple

from PIL import Image

WORK_EDGE = 800  # the estimate runs on a small copy: fast, and plenty for a fraction of a degree


def _profile_score(gray: Image.Image, angle: float) -> float:
    turned = gray.rotate(angle, resample=Image.BILINEAR, expand=False, fillcolor=255)
    rows: List[int] = list(turned.resize((1, turned.height), Image.BOX).getdata())
    mean = sum(rows) / len(rows)
    return sum((r - mean) ** 2 for r in rows) / len(rows)


def estimate_skew(path: str, max_angle: float = 10.0) -> Tuple[float, float]:
    """(counter-clockwise degrees that straighten the page, how much better than leaving it: score ratio)."""
    with Image.open(path) as im:
        gray = im.convert("L")
    gray.thumbnail((WORK_EDGE, WORK_EDGE))
    # crop the outer margin: page edges and scanner shadows are not text lines
    w, h = gray.size
    gray = gray.crop((int(w * 0.05), int(h * 0.05), int(w * 0.95), int(h * 0.95)))
    base = _profile_score(gray, 0.0) or 1e-9
    best_angle, best = 0.0, base
    for step, span in ((1.0, max_angle), (0.2, 1.0)):  # coarse, then fine around the best
        center = best_angle
        n = int(round(span / step))
        for i in range(-n, n + 1):
            a = round(center + i * step, 2)
            if abs(a) > max_angle or a == center:
                continue
            score = _profile_score(gray, a)
            if score > best:
                best_angle, best = a, score
    return best_angle, best / base


def deskew(path: str, max_angle: float = 10.0, min_angle: float = 0.5, min_gain: float = 1.15) -> float:
    """Rotate the page image in place when it is clearly tilted; returns the angle applied (0 = untouched).

    Small or doubtful corrections are skipped: a page that is already straight must stay pixel-identical.
    """
    angle, gain = estimate_skew(path, max_angle)
    if abs(angle) < min_angle or gain < min_gain:
        return 0.0
    with Image.open(path) as im:
        im.load()
        mode = im.mode
        fill = 255 if mode == "L" else (255, 255, 255, 255) if mode == "RGBA" else (255, 255, 255)
        out = im.convert("RGB").rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255)) \
            if mode not in ("L", "RGB", "RGBA") else im.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=fill)
    out.save(path, "PNG")
    return angle
