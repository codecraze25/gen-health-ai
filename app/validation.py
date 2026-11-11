"""Field rules shared by manual order input and PDF extraction.

Each check returns an error message (or None) instead of raising, so callers decide whether a
failure rejects the request (manual input) or nulls the field and records an issue (extraction).
"""

import re
from datetime import date

MIN_DOB = date(1900, 1, 1)
MAX_PLAUSIBLE_AGE_YEARS = 120

_NAME_RE = re.compile(r"^[^\W\d_]+(?:[ '\-.,][^\W\d_]*)*\.?$", re.UNICODE)


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def npi_checksum_ok(npi: str) -> bool:
    """CMS NPI check digit: Luhn over the 9 digits prefixed with 80840."""
    digits = [int(c) for c in "80840" + npi[:-1]]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return (10 - total % 10) % 10 == int(npi[-1])


def normalize_npi(value: str) -> str:
    return re.sub(r"[\s\-]", "", value)


def check_npi(npi: str) -> str | None:
    if not re.fullmatch(r"\d{10}", npi):
        return "NPI must be exactly 10 digits"
    if not npi_checksum_ok(npi):
        return "NPI fails the CMS check-digit (Luhn) validation"
    return None


def check_dob(dob: date, today: date | None = None) -> str | None:
    today = today or date.today()
    if dob > today:
        return "Date of birth is in the future"
    if dob < MIN_DOB:
        return f"Date of birth is before {MIN_DOB.isoformat()}"
    return None


def dob_warning(dob: date, today: date | None = None) -> str | None:
    today = today or date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if age > MAX_PLAUSIBLE_AGE_YEARS:
        return f"Implausible age ({age} years); verify date of birth"
    return None


def check_person_name(name: str) -> str | None:
    if not name:
        return "Name is empty"
    if len(name) > 100:
        return "Name is longer than 100 characters"
    if not _NAME_RE.match(name):
        return "Name contains invalid characters"
    return None
