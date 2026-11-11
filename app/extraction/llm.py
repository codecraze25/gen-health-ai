import base64
import logging
from typing import Protocol

from openai import OpenAI

from app.core.config import get_settings
from app.extraction.pdf import LoadedPdf
from app.extraction.schema import ExtractionResult

logger = logging.getLogger(__name__)

MAX_TEXT_CHARS_PER_PAGE = 6000

INSTRUCTIONS = """\
You extract data from durable medical equipment (DME) orders received by fax: prescriptions,
standard written orders, certificates of medical necessity, and the clinical notes faxed with them.
Pages may be scanned, skewed, rotated, low quality, or out of order.

Extract exactly these fields:

PATIENT: the person the equipment is ordered for. First name, last name, date of birth.
- Do not use names of guardians, insurance subscribers, emergency contacts, or staff.
- If the name is written "LAST, FIRST", split it correctly. Exclude middle names/initials and
  suffixes from first and last name.
- Date of birth only: never use order, visit, signature, fax, or onset dates. Normalize to
  YYYY-MM-DD. If the date is illegible, impossible, or ambiguous, return null.

ORDERING PROVIDER: the clinician who orders/prescribes the equipment and signs the order. Usually
labelled "Prescriber", "Ordering Physician", "Ordering Provider", or the signer of the order.
- NOT the referring physician, primary care physician, the DME supplier, the fax sender, or a
  clinician who only wrote supporting notes, unless they are also clearly the prescriber.
- provider_name: full name without credentials; put credentials (MD, DO, DPM, NP, PA...) in
  provider_credentials.
- provider_npi: the 10-digit NPI belonging to the ordering provider (not a supplier, group, or
  referring-provider NPI). Copy the digits exactly as printed, even if they look wrong. Never
  correct, complete, or infer digits.

RULES:
- Never guess. If a field is not explicitly present in the document, value is null and
  confidence is "low". Do not infer values from context or from other fields.
- evidence: copy the exact text from the page that contains the value (e.g. "DOB: 12/05/1900").
- confidence: "high" when clearly printed and unambiguous, "medium" when partially legible or
  inferred from layout, "low" when uncertain.
- If the document gives different values for the same field of the same person (e.g. two
  different DOBs for the patient, or two NPIs for the ordering provider), use the one on the order
  or prescription page and list the others in conflicting_values. Other people in other roles
  (e.g. a referring physician) are not conflicts; leave conflicting_values empty for them.
- Set multiple_patients_detected if the document contains orders for more than one patient.
"""


class ExtractionLLM(Protocol):
    model: str

    def extract(self, pdf: LoadedPdf) -> ExtractionResult: ...


class OpenAIExtractor:
    def __init__(self) -> None:
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        self.model = settings.openai_model
        self.reasoning_effort = settings.openai_reasoning_effort
        self.client = OpenAI(
            api_key=settings.openai_api_key,
            timeout=settings.openai_timeout_seconds,
            max_retries=2,
        )

    def _content(self, pdf: LoadedPdf) -> list[dict]:
        content: list[dict] = [
            {
                "type": "input_text",
                "text": f"The document has {pdf.page_count} pages. Non-blank pages follow.",
            }
        ]
        for page in pdf.pages:
            label = f"--- Page {page.number} ---"
            if page.text:
                label += (
                    "\nEmbedded text layer (may be incomplete; the image is authoritative):\n"
                    + page.text[:MAX_TEXT_CHARS_PER_PAGE]
                )
            content.append({"type": "input_text", "text": label})
            content.append(
                {
                    "type": "input_image",
                    "image_url": "data:image/jpeg;base64," + base64.b64encode(page.jpeg).decode(),
                    "detail": "high",
                }
            )
        return content

    def extract(self, pdf: LoadedPdf) -> ExtractionResult:
        kwargs = {}
        if self.reasoning_effort and self.model.startswith(("gpt-5", "o")):
            kwargs["reasoning"] = {"effort": self.reasoning_effort}
        response = self.client.responses.parse(
            model=self.model,
            instructions=INSTRUCTIONS,
            input=[{"role": "user", "content": self._content(pdf)}],
            text_format=ExtractionResult,
            **kwargs,
        )
        if response.output_parsed is None:
            raise RuntimeError("Model returned no parseable output")
        return response.output_parsed
