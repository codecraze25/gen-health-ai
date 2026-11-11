"""Generate synthetic DME order PDFs with known answers for scripts/eval.py.

Each case targets a failure mode seen in real faxed orders. Scanned cases are rasterized (no
text layer), optionally rotated, skewed, and speckled. Output: tests/fixtures/eval/*.pdf and
expected.json (the values that should be SAVED, i.e. after validation).

Usage: uv run python scripts/make_eval_pdfs.py
"""

import json
import random
import shutil
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "eval"


def npi_with_check_digit(base9: str) -> str:
    digits = [int(c) for c in "80840" + base9]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return base9 + str((10 - total % 10) % 10)


NPI_A = npi_with_check_digit("174820193")
NPI_B = npi_with_check_digit("163049275")
NPI_REFERRING = npi_with_check_digit("198273645")
NPI_ORDERING = npi_with_check_digit("150394827")
NPI_SUPPLIER = npi_with_check_digit("142857396")
NPI_E = npi_with_check_digit("187654320")


def write_page(doc: pymupdf.Document, text: str, font="helv", size=11, skew=0.0) -> None:
    page = doc.new_page()
    rect = pymupdf.Rect(54, 54, page.rect.width - 54, page.rect.height - 54)
    morph = (rect.tl, pymupdf.Matrix(skew)) if skew else None
    if text:
        page.insert_textbox(rect, text, fontname=font, fontsize=size, morph=morph)


def rasterize(
    doc: pymupdf.Document, dpi: int, rotate: int = 0, speckle: int = 0, seed: int = 0
) -> pymupdf.Document:
    rng = random.Random(seed)
    out = pymupdf.open()
    for page in doc:
        for _ in range(speckle):
            x, y = rng.uniform(0, page.rect.width), rng.uniform(0, page.rect.height)
            r = rng.uniform(0.4, 1.4)
            page.draw_rect(pymupdf.Rect(x, y, x + r, y + r), color=(0, 0, 0), fill=(0, 0, 0))
        pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
        w, h = page.rect.width, page.rect.height
        new = (
            out.new_page(width=h, height=w)
            if rotate in (90, 270)
            else out.new_page(width=w, height=h)
        )
        new.insert_image(new.rect, pixmap=pix, rotate=rotate)
    return out


FAX_HEADER = "FAX  01/16/2024  09:12AM   FROM: 617-555-0100   TO: 617-555-0199   P.{p}/{n}\n\n"


def case_clean_typed():
    doc = pymupdf.open()
    write_page(
        doc,
        "DURABLE MEDICAL EQUIPMENT ORDER\n\n"
        "Patient Name: James Okafor\nDate of Birth: 07/22/1958\nPhone: 617-555-0142\n"
        "Address: 14 Elm Street, Quincy, MA 02169\n\n"
        "Item: E0601 CPAP device, A7030 full face mask\nDiagnosis: G47.33 Obstructive sleep apnea\n"
        "Length of need: 99 months\n\n"
        f"Ordering Physician: Priya Natarajan, MD\nNPI: {NPI_A}\nPhone: 617-555-0177\n\n"
        "Signature: ____________________   Date: 01/12/2024",
    )
    return doc, {
        "patient_first_name": "James",
        "patient_last_name": "Okafor",
        "patient_dob": "1958-07-22",
        "provider_name": "Priya Natarajan",
        "provider_npi": NPI_A,
    }


def case_last_first_scanned():
    doc = pymupdf.open()
    write_page(
        doc,
        FAX_HEADER.format(p=1, n=1) + "PRESCRIPTION / DETAILED WRITTEN ORDER\n\n"
        "PATIENT: HERNANDEZ, LUIS A.          D.O.B.: 3-14-1962\nMRN: 00482913\n\n"
        "Equipment: K0001 Standard wheelchair; E0110 crutches\nDx: M17.11\n\n"
        f"Ordering Provider: Emily Chen, NP     NPI# {NPI_B}\n\n"
        "Provider signature: Emily Chen NP      Date signed: 01/10/2024",
        font="cour",
        size=10,
    )
    return rasterize(doc, dpi=110, speckle=400, seed=2), {
        "patient_first_name": "Luis",
        "patient_last_name": "Hernandez",
        "patient_dob": "1962-03-14",
        "provider_name": "Emily Chen",
        "provider_npi": NPI_B,
    }


def case_referring_trap_scanned():
    doc = pymupdf.open()
    write_page(
        doc,
        FAX_HEADER.format(p=1, n=1) + "OXYGEN ORDER - CERTIFICATE OF MEDICAL NECESSITY\n\n"
        f"Referring Physician: Michael Grant, MD   NPI: {NPI_REFERRING}\n\n"
        "Patient: Aisha Rahman\nDOB: 11/02/1947\n\n"
        "Order: E1390 Oxygen concentrator, 2 LPM continuous\nDx: J44.9 COPD\n\n"
        "ORDERING PHYSICIAN (must sign)\n"
        f"Name: Rachel Adams, DO\nNPI: {NPI_ORDERING}\n"
        "Signature: Rachel Adams DO     Date: 01/09/2024",
        font="tiro",
    )
    return rasterize(doc, dpi=130, speckle=150, seed=3), {
        "patient_first_name": "Aisha",
        "patient_last_name": "Rahman",
        "patient_dob": "1947-11-02",
        "provider_name": "Rachel Adams",
        "provider_npi": NPI_ORDERING,
    }


def case_missing_dob_and_npi():
    doc = pymupdf.open()
    write_page(
        doc,
        "Standard Written Order\n\nPatient: Grace Liu\nOrder Date: 01/15/2024\n"
        "Date of Service: 01/20/2024\n\nItem: E0143 Walker, folding, wheeled\n\n"
        "Prescriber: Daniel Kim, MD\nPhone: 555-0123   Fax: 555-0124\n\n"
        "Signed: Daniel Kim MD   01/15/2024",
    )
    return doc, {
        "patient_first_name": "Grace",
        "patient_last_name": "Liu",
        "patient_dob": None,
        "provider_name": "Daniel Kim",
        "provider_npi": None,
    }


def case_multipage_buried():
    doc = pymupdf.open()
    n = 6
    write_page(
        doc,
        FAX_HEADER.format(p=1, n=n) + "FAX COVER SHEET\n\nTo: Intake Department\n"
        f"From: Sunrise Medical Supply   Supplier NPI: {NPI_SUPPLIER}\n"
        "Re: New order - see attached\nPages: 6 including cover",
    )
    write_page(
        doc,
        FAX_HEADER.format(p=2, n=n) + "INSURANCE INFORMATION\n\nPrimary: Blue Cross PPO\n"
        "Subscriber: Robert Whitfield   Subscriber DOB: 02/02/1950\n"
        "Relationship of patient to subscriber: Spouse\nMember ID: XWB123456789",
    )
    write_page(doc, "")
    write_page(
        doc,
        FAX_HEADER.format(p=4, n=n) + "PROGRESS NOTE\n\nPt seen for worsening knee pain. "
        "Ambulates with difficulty. Recommend rollator. Follow up 6 weeks.\n"
        "Note author: Karen Ellis, PA-C",
    )
    write_page(
        doc,
        FAX_HEADER.format(p=5, n=n) + "DME PRESCRIPTION\n\nPatient: Linda Whitfield\n"
        "DOB: 09/30/1955\n\nItem: E0143 Rollator walker with seat\nDx: M17.0\n\n"
        f"Ordering physician: Thomas Brennan, MD\nNPI: {NPI_E}\n"
        "Signature: T. Brennan MD   Date: 01/11/2024",
    )
    write_page(doc, "")
    return rasterize(doc, dpi=120, speckle=120, seed=5), {
        "patient_first_name": "Linda",
        "patient_last_name": "Whitfield",
        "patient_dob": "1955-09-30",
        "provider_name": "Thomas Brennan",
        "provider_npi": NPI_E,
    }


def case_rotated_skewed_lowres():
    doc = pymupdf.open()
    write_page(
        doc,
        FAX_HEADER.format(p=1, n=1) + "HOSPITAL BED ORDER\n\nPatient Name: Owen Murphy\n"
        "Birthdate: 05/19/1940\n\nE0260 Semi-electric hospital bed with mattress\n\n"
        f"Physician: Sarah Lindqvist, MD   NPI {NPI_A}\nSigned 01/08/2024",
        size=13,
        skew=2.5,
    )
    return rasterize(doc, dpi=90, rotate=90, speckle=600, seed=6), {
        "patient_first_name": "Owen",
        "patient_last_name": "Murphy",
        "patient_dob": "1940-05-19",
        "provider_name": "Sarah Lindqvist",
        "provider_npi": NPI_A,
    }


CASES = {
    "clean_typed": case_clean_typed,
    "last_first_scanned": case_last_first_scanned,
    "referring_trap_scanned": case_referring_trap_scanned,
    "missing_dob_and_npi": case_missing_dob_and_npi,
    "multipage_buried": case_multipage_buried,
    "rotated_skewed_lowres": case_rotated_skewed_lowres,
}

SAMPLE_EXPECTED = {
    "patient_first_name": "Marie",
    "patient_last_name": "Curie",
    "patient_dob": "1900-12-05",
    "provider_name": "Arjun Raj",
    # Printed NPI 9182734556 fails the check digit, so nothing should be saved.
    "provider_npi": None,
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    expected = {}
    for name, build in CASES.items():
        doc, answers = build()
        doc.save(OUT / f"{name}.pdf", garbage=4, deflate=True)
        expected[f"{name}.pdf"] = answers
    shutil.copy(ROOT / "tests" / "fixtures" / "sample_cpap_fax.pdf", OUT / "sample_cpap_fax.pdf")
    expected["sample_cpap_fax.pdf"] = SAMPLE_EXPECTED
    (OUT / "expected.json").write_text(json.dumps(expected, indent=2) + "\n")
    print(f"Wrote {len(expected)} cases to {OUT}")


if __name__ == "__main__":
    main()
