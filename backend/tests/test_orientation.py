"""Sideways, upside-down and tilted pages: the upright tile is picked, and slight tilts are straightened locally."""
import asyncio
import base64
import io

from PIL import Image, ImageDraw

from pipeline.base import Context, FormDoc
from pipeline.deskew import deskew, estimate_skew
from pipeline.stages.classify import TILES, Classify, _tiles_b64, degrees_of


def _text_page(path, w=1200, h=1700):
    """A page of "text lines": short dark bars in rows, plus a dark corner mark to tell orientations apart."""
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    for row in range(120, h - 120, 48):
        x = 100
        while x < w - 160:
            d.rectangle([x, row, x + 70, row + 14], fill="black")
            x += 95
    d.rectangle([0, 0, 60, 60], fill=(200, 0, 0))  # top-left marker
    im.save(path)
    return str(path)


def _ctx(client=None, **cfg):
    return Context(settings=None, pipeline_cfg=cfg, senders_cfg={}, client=client)


def test_degrees_from_tile_and_from_older_answers():
    assert [degrees_of({"upright_tile": t}) for t in "ABCD"] == [0, 90, 180, 270]
    assert degrees_of({"upright_tile": " d "}) == 270
    assert degrees_of({"clockwise_degrees": 90}) == 90  # older answer shape still understood
    assert degrees_of({}) == 0 and degrees_of({"upright_tile": "Z"}) == 0


def test_tiles_show_the_page_turned_each_way(tmp_path):
    page = _text_page(tmp_path / "p.png")
    sheet = Image.open(io.BytesIO(base64.b64decode(_tiles_b64(page, tile=400)))).convert("RGB")
    assert sheet.size == (2 * 434, 2 * 434)

    def red_corner(x0, y0, w, h):
        """Which corner of the tile holds the red marker."""
        def red(x, y):
            r, g, b = sheet.getpixel((x, y))
            return r > 150 and g < 90 and b < 90
        corners = {"tl": (x0 + 3, y0 + 3), "tr": (x0 + w - 4, y0 + 3),
                   "bl": (x0 + 3, y0 + h - 4), "br": (x0 + w - 4, y0 + h - 4)}
        return [k for k, (x, y) in corners.items() if red(x, y)]

    # page thumbnail is 282x400 (portrait); turned 90/270 it is 400x282
    assert red_corner(34, 34, 282, 400) == ["tl"]               # A: as is
    assert red_corner(434 + 34, 34, 400, 282) == ["tr"]         # B: 90 clockwise
    assert red_corner(34, 434 + 34, 282, 400) == ["br"]         # C: 180
    assert red_corner(434 + 34, 434 + 34, 400, 282) == ["bl"]   # D: 270 clockwise
    assert TILES == {"A": 0, "B": 90, "C": 180, "D": 270}


def test_tilted_page_is_straightened_and_straight_page_untouched(tmp_path):
    page = _text_page(tmp_path / "p.png")
    straight = open(page, "rb").read()
    assert deskew(page) == 0.0
    assert open(page, "rb").read() == straight  # pixel-identical when already straight

    tilted = tmp_path / "t.png"
    Image.open(page).rotate(6, expand=True, fillcolor="white").save(tilted)
    angle, gain = estimate_skew(str(tilted))
    assert abs(angle + 6) <= 0.4 and gain > 1.5
    assert abs(deskew(str(tilted)) + 6) <= 0.4
    assert abs(estimate_skew(str(tilted))[0]) <= 0.4  # straight now


def test_a_photo_taken_at_a_large_angle_is_straightened(tmp_path):
    page = _text_page(tmp_path / "p.png")
    for turn in (15, -25, 40):
        tilted = tmp_path / f"t{turn}.png"
        Image.open(page).rotate(turn, expand=True, fillcolor="white").save(tilted)
        assert abs(deskew(str(tilted)) + turn) <= 0.4
        assert abs(estimate_skew(str(tilted))[0]) <= 0.4


class TileStub:
    def __init__(self, tile):
        self.tile = tile
        self.images = []

    async def call_tool(self, image_b64, media_type, prompt, tool, system=None):
        self.images.append(image_b64)
        return {"upright_tile": self.tile, "doc_type": "commitment"}


def test_classify_turns_an_upside_down_page_upright(tmp_path):
    upright = _text_page(tmp_path / "u.png")
    page = tmp_path / "p.png"
    Image.open(upright).rotate(180).save(page)  # arrives upside down
    form = FormDoc(batch_id=0, source_file_id=0, image_path=str(page))
    asyncio.run(Classify().run(form, _ctx(TileStub("C"))))
    assert Image.open(page).convert("RGB").getpixel((5, 5))[0] > 150  # red marker back at the top-left


def test_classify_straightens_a_tilted_page_even_when_the_check_fails(tmp_path):
    page = tmp_path / "p.png"
    Image.open(_text_page(tmp_path / "u.png")).rotate(-5, expand=True, fillcolor="white").save(page)

    class Broken:
        async def call_tool(self, **kw):
            raise RuntimeError("down")

    form = FormDoc(batch_id=0, source_file_id=0, image_path=str(page))
    asyncio.run(Classify().run(form, _ctx(Broken())))
    assert abs(estimate_skew(str(page))[0]) <= 0.4


def test_deskew_can_be_switched_off(tmp_path):
    page = tmp_path / "p.png"
    Image.open(_text_page(tmp_path / "u.png")).rotate(-5, expand=True, fillcolor="white").save(page)
    before = open(page, "rb").read()
    form = FormDoc(batch_id=0, source_file_id=0, image_path=str(page))
    asyncio.run(Classify().run(form, _ctx(TileStub("A"), orientation={"enabled": True, "deskew": False})))
    assert open(page, "rb").read() == before
