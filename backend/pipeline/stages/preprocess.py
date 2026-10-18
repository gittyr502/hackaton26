"""Stage 2 — preprocess: render PDF pages at the configured DPI; fix image rotation by EXIF.

Phase 2 hook: deskew / enhance with OpenCV.
"""
from pathlib import Path

from PIL import Image, ImageOps

from pipeline.base import Context, FormDoc


class Preprocess:
    def run(self, form: FormDoc, ctx: Context) -> FormDoc:
        dpi = ctx.pipeline_cfg.get("preprocess", {}).get("dpi", 200)
        pages_dir = Path(ctx.batch_dir) / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{form.source_file_id}"
        pages = []
        if form.mime == "application/pdf":
            import fitz  # PyMuPDF

            with fitz.open(form.file_path) as pdf:
                for i, page in enumerate(pdf):
                    out = pages_dir / f"{stem}_p{i + 1}.png"
                    page.get_pixmap(dpi=dpi).save(str(out))
                    pages.append(str(out))
        else:
            out = pages_dir / f"{stem}_p1.png"
            with Image.open(form.file_path) as im:
                im = ImageOps.exif_transpose(im)
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                im.save(out, "PNG")
            pages.append(str(out))
        if not pages:
            raise ValueError("no pages found")
        form.pages = pages
        return form
