"""Structured-output schema the vision model must fill.

Every field carries its evidence so a reviewer (and our validators) can see where it came from.
Adding a new extracted field means adding it here, in `FIELD_NAMES`, and on the Order model.
"""

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]


class ExtractedField(BaseModel):
    value: str | None = Field(
        description="The value exactly as it applies to this field, or null if not present."
    )
    source_page: int | None = Field(description="1-based page number the value was read from.")
    evidence: str | None = Field(
        description="Verbatim text copied from the document that contains the value."
    )
    confidence: Confidence
    conflicting_values: list[str] = Field(
        description="Other different values for this same field found elsewhere in the document."
    )


class ExtractionResult(BaseModel):
    patient_first_name: ExtractedField
    patient_last_name: ExtractedField
    patient_dob: ExtractedField = Field(description="Value normalized to YYYY-MM-DD.")
    provider_name: ExtractedField = Field(
        description="Ordering provider's full name without credentials (no MD, DO, NP, DPM)."
    )
    provider_credentials: str | None
    provider_npi: ExtractedField = Field(description="Digits only, copied exactly as printed.")
    multiple_patients_detected: bool
    document_notes: str | None = Field(
        description="Anything a reviewer should know: illegible areas, ambiguities, conflicts."
    )


FIELD_NAMES = (
    "patient_first_name",
    "patient_last_name",
    "patient_dob",
    "provider_name",
    "provider_npi",
)
