from dataclasses import dataclass, field

import pymupdf

RENDER_DPI = 150
MAX_RENDER_SIDE_PX = 2000
BLANK_PROBE_DPI = 20
BLANK_DARK_PIXEL_RATIO = 0.002


class PdfError(ValueError):
    """The upload is not a PDF we can process; the message is safe to show to the client."""


@dataclass
class PageImage:
    number: int  # 1-based, as printed in the original document
    text: str
    jpeg: bytes


@dataclass
class LoadedPdf:
    page_count: int
    pages: list[PageImage]
    skipped_blank_pages: list[int] = field(default_factory=list)
    truncated: bool = False

    @property
    def has_text_layer(self) -> bool:
        return any(p.text.strip() for p in self.pages)


def _is_blank(page: pymupdf.Page) -> bool:
    if page.get_text().strip():
        return False
    pix = page.get_pixmap(dpi=BLANK_PROBE_DPI, colorspace=pymupdf.csGRAY)
    samples = pix.samples
    dark = sum(1 for b in samples if b < 160)
    return dark / max(len(samples), 1) < BLANK_DARK_PIXEL_RATIO


def _render(page: pymupdf.Page) -> bytes:
    rect = page.rect
    longest_in = max(rect.width, rect.height) / 72
    dpi = min(RENDER_DPI, int(MAX_RENDER_SIDE_PX / longest_in)) if longest_in else RENDER_DPI
    pix = page.get_pixmap(dpi=max(dpi, 72))
    return pix.tobytes("jpeg", jpg_quality=85)


def load_pdf(data: bytes, max_pages: int) -> LoadedPdf:
    if not data.lstrip()[:5].startswith(b"%PDF"):
        raise PdfError("File is not a PDF")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PdfError("PDF is corrupt or unreadable") from exc

    with doc:
        if doc.needs_pass:
            raise PdfError("PDF is password-protected")
        if doc.page_count == 0:
            raise PdfError("PDF has no pages")

        result = LoadedPdf(page_count=doc.page_count, pages=[])
        for index, page in enumerate(doc):
            if len(result.pages) >= max_pages:
                result.truncated = True
                break
            if _is_blank(page):
                result.skipped_blank_pages.append(index + 1)
                continue
            result.pages.append(
                PageImage(number=index + 1, text=page.get_text().strip(), jpeg=_render(page))
            )

    if not result.pages:
        raise PdfError("PDF contains only blank pages")
    return result
