import pymupdf
import pytest

from app.api.deps import get_extractor
from app.extraction import service
from app.extraction.nppes import NppesRecord
from app.extraction.schema import ExtractedField, ExtractionResult
from app.main import app

ORDER_TEXT = (
    "Standard Written Order\n"
    "Patient: Marie Curie   DOB: 12/05/1950\n"
    "Prescriber: Arjun Raj DPM   NPI: 1234567893\n"
)


def make_pdf(pages: list[str], password: str | None = None) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=11)
    kwargs = {}
    if password:
        kwargs = {
            "encryption": pymupdf.PDF_ENCRYPT_AES_256,
            "user_pw": password,
            "owner_pw": password,
        }
    return doc.tobytes(**kwargs)


def field(value, evidence=None, page=1, confidence="high", conflicts=None) -> ExtractedField:
    return ExtractedField(
        value=value,
        source_page=page if value else None,
        evidence=evidence if evidence is not None else value,
        confidence=confidence,
        conflicting_values=conflicts or [],
    )


def result(**overrides) -> ExtractionResult:
    fields = {
        "patient_first_name": field("Marie", "Patient: Marie Curie"),
        "patient_last_name": field("Curie", "Patient: Marie Curie"),
        "patient_dob": field("1950-12-05", "DOB: 12/05/1950"),
        "provider_name": field("Arjun Raj", "Prescriber: Arjun Raj DPM"),
        "provider_npi": field("1234567893", "NPI: 1234567893"),
        "provider_credentials": "DPM",
        "multiple_patients_detected": False,
        "document_notes": None,
    }
    fields.update(overrides)
    return ExtractionResult(**fields)


class FakeExtractor:
    model = "fake-model"

    def __init__(self, outcome: ExtractionResult | Exception):
        self.outcome = outcome
        self.calls = 0

    def extract(self, pdf):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.fixture
def use_extractor():
    def _use(outcome) -> FakeExtractor:
        fake = FakeExtractor(outcome)
        app.dependency_overrides[get_extractor] = lambda: fake
        return fake

    return _use


@pytest.fixture(autouse=True)
def no_network_nppes(monkeypatch):
    monkeypatch.setattr(service, "lookup_npi", lambda npi, timeout: None)
    monkeypatch.setattr(service.get_settings(), "nppes_lookup_enabled", False)


def upload(client, auth, data: bytes, name: str = "order.pdf"):
    return client.post(
        "/orders/upload", headers=auth, files={"file": (name, data, "application/pdf")}
    )


def codes(order) -> set[tuple[str, str]]:
    return {(i["field"], i["code"]) for i in order["validation_issues"]}


def test_clean_extraction_creates_ready_order(client, auth, use_extractor):
    use_extractor(result())
    resp = upload(client, auth, make_pdf([ORDER_TEXT]))
    assert resp.status_code == 201, resp.text
    order = resp.json()
    assert order["status"] == "ready"
    assert order["validation_issues"] == []
    assert order["patient_dob"] == "1950-12-05"
    assert order["provider_npi"] == "1234567893"
    assert order["source_filename"] == "order.pdf"
    assert len(order["source_sha256"]) == 64
    assert order["extraction"]["model"] == "fake-model"
    assert order["extraction"]["fields"]["provider_npi"]["evidence"] == "NPI: 1234567893"


def test_missing_field_is_null_not_guessed(client, auth, use_extractor):
    use_extractor(result(patient_dob=field(None, confidence="low")))
    order = upload(client, auth, make_pdf([ORDER_TEXT])).json()
    assert order["patient_dob"] is None
    assert ("patient_dob", "missing") in codes(order)
    assert order["status"] == "needs_review"


def test_invalid_npi_is_rejected_and_reported(client, auth, use_extractor):
    use_extractor(result(provider_npi=field("9182734556", "NPI: 9182734556")))
    order = upload(client, auth, make_pdf(["NPI: 9182734556"])).json()
    assert order["provider_npi"] is None
    issue = next(i for i in order["validation_issues"] if i["field"] == "provider_npi")
    assert issue["code"] == "invalid"
    assert issue["rejected_value"] == "9182734556"


@pytest.mark.parametrize("bad_dob", ["2024-02-30", "12/05/1950", "2999-01-01"])
def test_invalid_dob_is_rejected(client, auth, use_extractor, bad_dob):
    use_extractor(result(patient_dob=field(bad_dob, "DOB: ?")))
    order = upload(client, auth, make_pdf([ORDER_TEXT])).json()
    assert order["patient_dob"] is None
    assert ("patient_dob", "invalid") in codes(order)


def test_implausible_dob_kept_but_flagged(client, auth, use_extractor):
    use_extractor(result(patient_dob=field("1900-12-05", "DOB: 12/05/1900")))
    order = upload(client, auth, make_pdf(["DOB: 12/05/1900"])).json()
    assert order["patient_dob"] == "1900-12-05"
    assert ("patient_dob", "implausible") in codes(order)
    assert order["status"] == "needs_review"


def test_evidence_not_on_page_is_flagged(client, auth, use_extractor):
    use_extractor(result(patient_last_name=field("Curie", "Patient: Pierre Curie")))
    order = upload(client, auth, make_pdf([ORDER_TEXT])).json()
    assert ("patient_last_name", "evidence_not_found") in codes(order)


def test_npi_not_in_its_own_evidence_is_flagged(client, auth, use_extractor):
    use_extractor(result(provider_npi=field("1234567893", "NPI: 1245319599")))
    order = upload(client, auth, make_pdf([ORDER_TEXT])).json()
    assert ("provider_npi", "evidence_mismatch") in codes(order)


def test_low_confidence_and_conflicts_are_flagged(client, auth, use_extractor):
    use_extractor(
        result(
            patient_first_name=field("Marie", "Patient: Marie Curie", confidence="low"),
            patient_dob=field("1950-12-05", "DOB: 12/05/1950", conflicts=["1950-05-12"]),
        )
    )
    order = upload(client, auth, make_pdf([ORDER_TEXT])).json()
    assert ("patient_first_name", "low_confidence") in codes(order)
    assert ("patient_dob", "conflict") in codes(order)
    assert order["patient_first_name"] == "Marie"


def test_multiple_patients_flagged(client, auth, use_extractor):
    use_extractor(result(multiple_patients_detected=True))
    order = upload(client, auth, make_pdf([ORDER_TEXT])).json()
    assert ("document", "multiple_patients") in codes(order)


def test_model_failure_still_creates_reviewable_order(client, auth, use_extractor):
    use_extractor(TimeoutError("model timed out"))
    resp = upload(client, auth, make_pdf([ORDER_TEXT]))
    assert resp.status_code == 201
    order = resp.json()
    assert ("document", "extraction_failed") in codes(order)
    assert all(order[f] is None for f in ("patient_first_name", "provider_npi"))

    patched = client.patch(
        f"/orders/{order['id']}",
        headers=auth,
        json={
            "patient_first_name": "Marie",
            "patient_last_name": "Curie",
            "patient_dob": "1950-12-05",
            "provider_name": "Arjun Raj",
            "provider_npi": "1234567893",
        },
    ).json()
    assert patched["status"] == "ready"
    assert patched["validation_issues"] == []


def test_user_edit_resolves_field_issue(client, auth, use_extractor):
    use_extractor(result(provider_npi=field("9182734556", "NPI: 9182734556")))
    order = upload(client, auth, make_pdf([ORDER_TEXT + "NPI: 9182734556"])).json()
    assert order["status"] == "needs_review"
    patched = client.patch(
        f"/orders/{order['id']}", headers=auth, json={"provider_npi": "1234567893"}
    ).json()
    assert patched["status"] == "ready"


def test_blank_pages_are_skipped(client, auth, use_extractor):
    fake = use_extractor(result())
    order = upload(client, auth, make_pdf([ORDER_TEXT, "", ""])).json()
    assert order["extraction"]["skipped_blank_pages"] == [2, 3]
    assert order["extraction"]["pages_processed"] == [1]
    assert fake.calls == 1


def test_upload_requires_auth(client, use_extractor):
    use_extractor(result())
    resp = client.post("/orders/upload", files={"file": ("a.pdf", make_pdf([ORDER_TEXT]))})
    assert resp.status_code == 401


def test_uploaded_order_is_private(client, make_user, use_extractor):
    use_extractor(result())
    alice, bob = make_user("alice@example.com"), make_user("bob@example.com")
    order = upload(client, alice, make_pdf([ORDER_TEXT])).json()
    assert client.get(f"/orders/{order['id']}", headers=bob).status_code == 404


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (b"hello, not a pdf", 415),
        (b"%PDF-1.7 garbage that is not a real pdf", 422),
        (make_pdf(["", ""]), 422),
        (make_pdf([ORDER_TEXT], password="secret"), 422),
    ],
    ids=["not-pdf", "corrupt", "blank-only", "encrypted"],
)
def test_bad_uploads_rejected_without_calling_model(client, auth, use_extractor, data, status):
    fake = use_extractor(result())
    resp = upload(client, auth, data)
    assert resp.status_code == status, resp.text
    assert fake.calls == 0


def test_oversized_upload_rejected(client, auth, use_extractor, monkeypatch):
    monkeypatch.setattr(service.get_settings(), "max_upload_mb", 0)
    use_extractor(result())
    assert upload(client, auth, make_pdf([ORDER_TEXT])).status_code == 413


def test_nppes_name_mismatch_flagged(client, auth, use_extractor, monkeypatch):
    monkeypatch.setattr(service.get_settings(), "nppes_lookup_enabled", True)
    monkeypatch.setattr(
        service,
        "lookup_npi",
        lambda npi, timeout: NppesRecord(npi, "GREGORY HOUSE", "GREGORY", "HOUSE", "NPI-1"),
    )
    use_extractor(result())
    order = upload(client, auth, make_pdf([ORDER_TEXT])).json()
    assert ("provider_npi", "npi_name_mismatch") in codes(order)
    assert order["extraction"]["nppes"]["status"] == "found"


def test_nppes_outage_does_not_block(client, auth, use_extractor, monkeypatch):
    import httpx

    def boom(npi, timeout):
        raise httpx.ConnectTimeout("down")

    monkeypatch.setattr(service.get_settings(), "nppes_lookup_enabled", True)
    monkeypatch.setattr(service, "lookup_npi", boom)
    use_extractor(result())
    order = upload(client, auth, make_pdf([ORDER_TEXT])).json()
    assert order["status"] == "ready"
    assert order["extraction"]["nppes"]["status"] == "unavailable"
