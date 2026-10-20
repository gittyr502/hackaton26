"""Stage 1 — ingest: identify the uploaded file type; convert HEIC to PNG."""
from pathlib import Path

from PIL import Image

from pipeline.base import Context, FileProblem, FormDoc

SIGNATURES = [
    (b"%PDF", "application/pdf"),
    (b"\x89PNG", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"II*\x00", "image/tiff"),
    (b"MM\x00*", "image/tiff"),
]


def sniff(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(16)
    if not head:
        raise FileProblem("empty_file", "empty file")
    return sniff_bytes(head)


def sniff_bytes(head: bytes) -> str:
    """The file type from its first bytes (never from the extension, which may lie)."""
    for sig, mime in SIGNATURES:
        if head.startswith(sig):
            return mime
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"heim", b"heis", b"hevc"):
        return "image/heic"
    raise FileProblem("unsupported_type", "unsupported file type")


class Ingest:
    def run(self, form: FormDoc, ctx: Context) -> FormDoc:
        path = Path(form.file_path)
        mime = sniff(path)
        if mime == "image/heic":
            import pillow_heif

            pillow_heif.register_heif_opener()
            out = path.with_suffix(".png")
            try:
                with Image.open(path) as im:
                    im.save(out, "PNG")
            except Exception as e:
                raise FileProblem("corrupt_file", f"unreadable HEIC: {type(e).__name__}") from e
            path, mime = out, "image/png"
        form.file_path, form.mime = str(path), mime
        return form
