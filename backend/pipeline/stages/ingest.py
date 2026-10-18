"""Stage 1 — ingest: identify the uploaded file type; convert HEIC to PNG."""
from pathlib import Path

from PIL import Image

from pipeline.base import Context, FormDoc

SIGNATURES = [
    (b"%PDF", "application/pdf"),
    (b"\x89PNG", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
]


def sniff(path: Path) -> str:
    head = path.read_bytes()[:16]
    for sig, mime in SIGNATURES:
        if head.startswith(sig):
            return mime
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"heim", b"heis", b"hevc"):
        return "image/heic"
    raise ValueError("unsupported file type")


class Ingest:
    def run(self, form: FormDoc, ctx: Context) -> FormDoc:
        path = Path(form.file_path)
        mime = sniff(path)
        if mime == "image/heic":
            import pillow_heif

            pillow_heif.register_heif_opener()
            out = path.with_suffix(".png")
            with Image.open(path) as im:
                im.save(out, "PNG")
            path, mime = out, "image/png"
        form.file_path, form.mime = str(path), mime
        return form
