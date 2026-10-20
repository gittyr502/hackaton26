"""Stage 2 — preprocess: render PDF pages at the configured DPI; fix image rotation by EXIF.

A damaged upload never crashes the batch: it fails with a code the UI explains
(empty / corrupt / password-protected / too many pages / too large). A PDF that is
only partly damaged keeps its good pages and warns that pages are missing.

Phase 2 hook: deskew / enhance with OpenCV.
"""
from pathlib import Path

from PIL import Image, ImageFile, ImageOps

from app.logging_utils import get_logger, log_event
from pipeline.base import Context, FileProblem, FormDoc

log = get_logger("preprocess")


def _render_pdf(form: FormDoc, cfg: dict, pages_dir: Path, stem: str) -> list:
    import fitz  # PyMuPDF

    dpi = cfg.get("dpi", 200)
    max_pages = cfg.get("max_pages", 100)
    try:
        pdf = fitz.open(form.file_path)
    except Exception as e:
        raise FileProblem("corrupt_file", f"unreadable PDF: {type(e).__name__}") from e
    pages = []
    with pdf:
        if pdf.needs_pass:
            raise FileProblem("password_protected", "password-protected PDF")
        if pdf.page_count == 0:
            raise FileProblem("corrupt_file", "no pages found")
        if pdf.page_count > max_pages:
            raise FileProblem("too_many_pages", f"{pdf.page_count} pages (max {max_pages})")
        if getattr(pdf, "is_repaired", False):
            form.file_warnings.append("file_repaired")  # truncated / damaged: what could be read is kept
        bad = 0
        for i in range(pdf.page_count):
            out = pages_dir / f"{stem}_p{i + 1}.png"
            try:
                pdf[i].get_pixmap(dpi=dpi).save(str(out))
            except Exception as e:  # one bad page must not lose the others
                bad += 1
                log_event(log, "pdf_page_failed", source_file_id=form.source_file_id, page=i + 1,
                          error=type(e).__name__)
                continue
            pages.append(str(out))
    if bad:
        form.file_warnings.append("pages_missing")
    if not pages:
        raise FileProblem("corrupt_file", "no readable pages")
    return pages


def _open_image(path: str, form: FormDoc, max_pixels: int) -> Image.Image:
    """Load the image fully; a cut-off upload is read as far as it goes and flagged for review."""
    old_max = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels
    try:
        try:
            im = Image.open(path)
            im.load()
            return im
        except Image.DecompressionBombError as e:
            raise FileProblem("image_too_large", "image too large") from e
        except OSError:
            pass  # truncated: try again keeping what arrived
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        try:
            im = Image.open(path)
            im.load()
        except Exception as e:
            raise FileProblem("corrupt_file", f"unreadable image: {type(e).__name__}") from e
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = False
        form.add_form_reason("truncated_image")
        return im
    except FileProblem:
        raise
    except Exception as e:
        raise FileProblem("corrupt_file", f"unreadable image: {type(e).__name__}") from e
    finally:
        Image.MAX_IMAGE_PIXELS = old_max


class Preprocess:
    def run(self, form: FormDoc, ctx: Context) -> FormDoc:
        cfg = ctx.pipeline_cfg.get("preprocess", {})
        pages_dir = Path(ctx.batch_dir) / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{form.source_file_id}"
        if form.mime == "application/pdf":
            pages = _render_pdf(form, cfg, pages_dir, stem)
        else:
            out = pages_dir / f"{stem}_p1.png"
            im = _open_image(form.file_path, form, cfg.get("max_image_pixels", 120_000_000))
            with im:
                im = ImageOps.exif_transpose(im)
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                max_edge = cfg.get("max_edge_px", 6000)
                if max(im.size) > max_edge:  # huge photos: same reading, far less memory and upload
                    im.thumbnail((max_edge, max_edge))
                im.save(out, "PNG")
            pages = [str(out)]
        form.pages = pages
        return form
