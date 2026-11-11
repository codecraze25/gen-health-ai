from dataclasses import dataclass, field

import pymupdf

RENDER_DPI = 150
MAX_RENDER_SIDE_PX = 2000
# Thin scanned text washes out at very low DPI, so probe at 40 DPI with a light threshold. Content
# pages measure >1% ink; err toward keeping pages, since dropping one loses data.
BLANK_PROBE_DPI = 40
BLANK_INK_THRESHOLD = 220
BLANK_INK_RATIO = 0.001
ORIENTATION_PROBE_DPI = 40
SIDEWAYS_RATIO = 2.0


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
    rotated_pages: list[int] = field(default_factory=list)
    truncated: bool = False

    @property
    def has_text_layer(self) -> bool:
        return any(p.text.strip() for p in self.pages)


def _is_blank(page: pymupdf.Page) -> bool:
    if page.get_text().strip():
        return False
    pix = page.get_pixmap(dpi=BLANK_PROBE_DPI, colorspace=pymupdf.csGRAY)
    samples = pix.samples
    ink = sum(1 for b in samples if b < BLANK_INK_THRESHOLD)
    return ink / max(len(samples), 1) < BLANK_INK_RATIO


def _profile_contrast(values: list[int]) -> float:
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    return sum((v - mean) ** 2 for v in values) / len(values) / mean**2


def _is_sideways(page: pymupdf.Page) -> bool:
    """Detects text running vertically (a page scanned sideways) without OCR.

    Horizontal text lines alternate ink and whitespace row by row, so the row ink profile varies
    far more than the column profile. Vision models misread sideways text noticeably more often.
    """
    pix = page.get_pixmap(dpi=ORIENTATION_PROBE_DPI, colorspace=pymupdf.csGRAY)
    w, h, s = pix.width, pix.height, pix.samples
    rows = [sum(1 for b in s[y * w : (y + 1) * w] if b < 160) for y in range(h)]
    cols = [sum(1 for y in range(h) if s[y * w + x] < 160) for x in range(w)]
    row_c, col_c = _profile_contrast(rows), _profile_contrast(cols)
    return col_c > row_c * SIDEWAYS_RATIO


def _render(page: pymupdf.Page, rotate: int = 0) -> bytes:
    rect = page.rect
    longest_in = max(rect.width, rect.height) / 72
    dpi = min(RENDER_DPI, int(MAX_RENDER_SIDE_PX / longest_in)) if longest_in else RENDER_DPI
    zoom = max(dpi, 72) / 72
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom).prerotate(rotate))
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
            rotate = 90 if _is_sideways(page) else 0
            if rotate:
                result.rotated_pages.append(index + 1)
            result.pages.append(
                PageImage(
                    number=index + 1, text=page.get_text().strip(), jpeg=_render(page, rotate)
                )
            )

    if not result.pages:
        raise PdfError("PDF contains only blank pages")
    return result
