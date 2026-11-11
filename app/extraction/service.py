"""Turns an uploaded PDF into validated order fields.

The model only proposes values. Code decides what is saved: a value that is missing, malformed, or
fails a check is saved as null with an issue explaining why, so nothing is guessed. Values that pass
but look suspicious are kept and flagged, which leaves the order in `needs_review`.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

from app import validation as v
from app.core.config import get_settings
from app.extraction.llm import ExtractionLLM
from app.extraction.nppes import lookup_npi
from app.extraction.pdf import LoadedPdf, load_pdf
from app.extraction.schema import FIELD_NAMES, ExtractedField, ExtractionResult

logger = logging.getLogger(__name__)

NAME_FIELDS = ("patient_first_name", "patient_last_name", "provider_name")


@dataclass
class ExtractionOutcome:
    fields: dict[str, Any] = field(default_factory=lambda: dict.fromkeys(FIELD_NAMES))
    issues: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def issue(
        self,
        field_name: str,
        code: str,
        message: str,
        severity: str = "error",
        rejected_value: str | None = None,
    ) -> None:
        self.issues.append(
            {
                "field": field_name,
                "code": code,
                "message": message,
                "severity": severity,
                "rejected_value": rejected_value,
            }
        )


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _validate_value(name: str, raw: str, out: ExtractionOutcome) -> Any:
    """Returns the cleaned value, or None after recording why it was rejected."""
    if name in NAME_FIELDS:
        value = v.normalize_whitespace(raw)
        if error := v.check_person_name(value):
            out.issue(name, "invalid", error, rejected_value=raw)
            return None
        return value

    if name == "patient_dob":
        try:
            dob = date.fromisoformat(raw.strip())
        except ValueError:
            out.issue(name, "invalid", "Not a valid calendar date", rejected_value=raw)
            return None
        if error := v.check_dob(dob):
            out.issue(name, "invalid", error, rejected_value=raw)
            return None
        if warning := v.dob_warning(dob):
            out.issue(name, "implausible", warning, severity="warning")
        return dob

    if name == "provider_npi":
        value = v.normalize_npi(raw)
        if error := v.check_npi(value):
            out.issue(name, "invalid", error, rejected_value=raw)
            return None
        return value

    raise ValueError(f"Unknown field {name}")


def _check_grounding(name: str, extracted: ExtractedField, pdf: LoadedPdf, out: ExtractionOutcome):
    value, evidence = extracted.value or "", extracted.evidence or ""
    page_numbers = {p.number for p in pdf.pages}
    if extracted.source_page not in page_numbers:
        out.issue(name, "bad_source_page", "Model cited a page that was not provided", "warning")
        return

    if not evidence:
        out.issue(name, "no_evidence", "No supporting text was quoted", "warning")
        return
    if name == "provider_npi" and value and _digits(value) not in _digits(evidence):
        out.issue(name, "evidence_mismatch", "Quoted text does not contain the NPI", "warning")
    if name in NAME_FIELDS and value and _squash(value) not in _squash(evidence):
        out.issue(name, "evidence_mismatch", "Quoted text does not contain the name", "warning")

    page_text = next(p.text for p in pdf.pages if p.number == extracted.source_page)
    if page_text and _squash(evidence) not in _squash(page_text):
        out.issue(
            name, "evidence_not_found", "Quoted text was not found on the cited page", "warning"
        )


def _check_nppes(out: ExtractionOutcome) -> None:
    npi, provider_name = out.fields["provider_npi"], out.fields["provider_name"]
    try:
        record = lookup_npi(npi, timeout=get_settings().nppes_timeout_seconds)
    except httpx.HTTPError as exc:
        out.metadata["nppes"] = {"status": "unavailable", "error": type(exc).__name__}
        return

    if record is None:
        out.metadata["nppes"] = {"status": "not_found"}
        out.issue("provider_npi", "npi_not_registered", "NPI not found in NPPES", "warning")
        return

    out.metadata["nppes"] = {
        "status": "found",
        "name": record.name,
        "enumeration_type": record.enumeration_type,
    }
    if record.enumeration_type == "NPI-2":
        out.issue(
            "provider_npi",
            "organization_npi",
            f"NPI belongs to an organization ({record.name}), not an individual provider",
            "warning",
        )
    elif (
        provider_name
        and record.last_name
        and record.last_name.lower() not in _squash(provider_name).split()
    ):
        out.issue(
            "provider_npi",
            "npi_name_mismatch",
            f"NPPES lists this NPI as {record.name}",
            "warning",
        )


def validate_extraction(result: ExtractionResult, pdf: LoadedPdf, out: ExtractionOutcome) -> None:
    for name in FIELD_NAMES:
        extracted: ExtractedField = getattr(result, name)
        out.metadata["fields"][name] = extracted.model_dump()

        if extracted.value is None or not extracted.value.strip():
            out.issue(name, "missing", "Not found in the document")
            continue

        value = _validate_value(name, extracted.value, out)
        out.fields[name] = value
        if value is None:
            continue

        _check_grounding(name, extracted, pdf, out)
        if extracted.confidence == "low":
            out.issue(name, "low_confidence", "Model reported low confidence", "warning")
        if extracted.conflicting_values:
            out.issue(
                name,
                "conflict",
                "Document contains other values: " + "; ".join(extracted.conflicting_values),
                "warning",
            )

    out.metadata["provider_credentials"] = result.provider_credentials
    out.metadata["document_notes"] = result.document_notes
    if result.multiple_patients_detected:
        out.issue("document", "multiple_patients", "Document appears to cover several patients")

    if out.fields["provider_npi"] and get_settings().nppes_lookup_enabled:
        _check_nppes(out)


def extract_order(data: bytes, extractor: ExtractionLLM) -> ExtractionOutcome:
    """Raises PdfError for unusable uploads; model failures become issues, not exceptions."""
    settings = get_settings()
    pdf = load_pdf(data, max_pages=settings.max_pdf_pages)

    out = ExtractionOutcome()
    out.metadata = {
        "model": extractor.model,
        "page_count": pdf.page_count,
        "pages_processed": [p.number for p in pdf.pages],
        "skipped_blank_pages": pdf.skipped_blank_pages,
        "has_text_layer": pdf.has_text_layer,
        "fields": {},
    }
    if pdf.truncated:
        out.issue(
            "document",
            "truncated",
            f"Only the first {settings.max_pdf_pages} non-blank pages were processed",
            "warning",
        )

    started = time.perf_counter()
    try:
        result = extractor.extract(pdf)
    except Exception as exc:
        logger.exception("extraction model call failed")
        out.metadata["error"] = type(exc).__name__
        out.issue("document", "extraction_failed", "Automatic extraction failed; enter manually")
        return out
    finally:
        out.metadata["duration_ms"] = round((time.perf_counter() - started) * 1000)

    validate_extraction(result, pdf, out)
    return out
