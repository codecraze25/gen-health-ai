from pathlib import Path

import pytest

from app.extraction.pdf import PdfError, load_pdf

EVAL = Path(__file__).parent / "fixtures" / "eval"


def test_sideways_scan_is_rotated_upright():
    pdf = load_pdf((EVAL / "rotated_skewed_lowres.pdf").read_bytes(), max_pages=30)
    assert pdf.rotated_pages == [1]


def test_upright_pages_are_not_rotated():
    for name in ("clean_typed.pdf", "last_first_scanned.pdf", "multipage_buried.pdf"):
        pdf = load_pdf((EVAL / name).read_bytes(), max_pages=30)
        assert pdf.rotated_pages == [], name


def test_sparse_scanned_order_is_not_mistaken_for_blank():
    pdf = load_pdf((EVAL / "last_first_scanned.pdf").read_bytes(), max_pages=30)
    assert [p.number for p in pdf.pages] == [1]


def test_sample_fax_trailing_blank_page_skipped():
    pdf = load_pdf((EVAL / "sample_cpap_fax.pdf").read_bytes(), max_pages=30)
    assert pdf.skipped_blank_pages == [4]
    assert not pdf.has_text_layer


def test_page_cap_truncates():
    pdf = load_pdf((EVAL / "multipage_buried.pdf").read_bytes(), max_pages=2)
    assert pdf.truncated
    assert len(pdf.pages) == 2


def test_rejects_non_pdf():
    with pytest.raises(PdfError):
        load_pdf(b"GIF89a...", max_pages=30)
