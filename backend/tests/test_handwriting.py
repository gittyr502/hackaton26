"""Handwriting: never ok after one read; zoomed crops confirm values or recover empty names/IDs."""
import asyncio
import base64
import io

from PIL import Image

from pipeline.base import Context, FieldResult, FormDoc
from pipeline.crops import crop_b64, halves_b64
from pipeline.stages.confidence import Confidence


class Stub:
    def __init__(self, second):
        self.second = second
        self.calls = []

    async def call_tool(self, image_b64, media_type, prompt, tool, system=None):
        self.calls.append((media_type, list(tool["input_schema"]["properties"])))
        return self.second


def _page(tmp_path):
    p = tmp_path / "page.png"
    Image.new("RGB", (1000, 1400), "white").save(p)
    return str(p)


def _ctx(client):
    return Context(settings=None, client=client, senders_cfg={},
                   pipeline_cfg={"confidence": {"threshold": 0.85}, "double_check": {"enabled": True}})


def _run(form, client):
    return asyncio.run(Confidence().run(form, _ctx(client)))


def _size(b64):
    with Image.open(io.BytesIO(base64.b64decode(b64))) as im:
        return im.size


def test_crop_upscales_small_box_and_needs_a_box(tmp_path):
    page = _page(tmp_path)
    w, h = _size(crop_b64(page, [0.6, 0.7, 0.8, 0.72]))
    assert w >= 1000 and h > 0
    assert crop_b64(page, None) is None
    assert [_size(x)[0] for x in halves_b64(page)] == [1000, 1000]


def test_handwritten_high_confidence_is_review_without_double_check(tmp_path):
    form = FormDoc(batch_id=0, source_file_id=0, image_path=_page(tmp_path), fields={
        "full_name": FieldResult(value="ישראל ישראלי", confidence=0.99, handwritten=True)})
    ctx = _ctx(None)
    ctx.pipeline_cfg["double_check"]["enabled"] = False
    out = asyncio.run(Confidence().run(form, ctx))
    assert out.fields["full_name"].level == "review"
    assert any(r["code"] == "handwritten" for r in out.fields["full_name"].reasons)


def test_crop_agreement_upgrades_handwritten_to_ok(tmp_path):
    form = FormDoc(batch_id=0, source_file_id=0, image_path=_page(tmp_path), fields={
        "full_name": FieldResult(value="ישראל ישראלי", confidence=0.9, handwritten=True,
                                 box=[0.6, 0.7, 0.8, 0.72])})
    client = Stub({"full_name": {"value": "ישראל  ישראלי", "confidence": 0.9, "legible": True}})
    out = _run(form, client)
    assert out.fields["full_name"].level == "ok"
    assert client.calls == [("image/png", ["full_name"])]  # one zoomed crop, one field


def test_empty_name_recovered_on_zoom_is_review_never_ok(tmp_path):
    form = FormDoc(batch_id=0, source_file_id=0, image_path=_page(tmp_path), fields={
        "full_name": FieldResult(value=None, box=[0.6, 0.7, 0.8, 0.72])})
    client = Stub({"full_name": {"value": "ישראל ישראלי", "confidence": 0.99, "legible": True}})
    f = _run(form, client).fields["full_name"]
    assert f.value == "ישראל ישראלי" and f.level == "review"
    assert any(r["code"] == "recovered_on_zoom" for r in f.reasons)


def test_recovered_id_is_normalized_and_validated(tmp_path):
    form = FormDoc(batch_id=0, source_file_id=0, image_path=_page(tmp_path), fields={
        "id_number": FieldResult(value=None)})  # no box: page halves are read
    client = Stub({"id_number": {"value": "011223344", "confidence": 0.99, "legible": True}})
    f = _run(form, client).fields["id_number"]
    assert f.value == "11223344" and f.level == "review"
    assert len(client.calls) == 2
    assert not any(r["code"] == "invalid_id_checksum" for r in f.reasons)


def test_empty_field_stays_empty_when_zoom_finds_nothing(tmp_path):
    form = FormDoc(batch_id=0, source_file_id=0, image_path=_page(tmp_path), fields={
        "full_name": FieldResult(value=None, box=[0.1, 0.1, 0.3, 0.12])})
    f = _run(form, Stub({"full_name": {"value": None, "confidence": 0, "legible": False}})).fields["full_name"]
    assert f.value is None and f.level == "empty" and not f.reasons
