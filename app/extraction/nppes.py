"""Cross-check an NPI against the public CMS NPPES registry (no API key required)."""

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

NPPES_URL = "https://npiregistry.cms.hhs.gov/api/"


@dataclass
class NppesRecord:
    npi: str
    name: str
    first_name: str | None
    last_name: str | None
    enumeration_type: str


def lookup_npi(npi: str, timeout: float = 5.0) -> NppesRecord | None:
    """Returns the registry record, None if the NPI is not registered.

    Raises httpx.HTTPError on network failure so callers can distinguish "not found" from
    "could not check".
    """
    resp = httpx.get(NPPES_URL, params={"version": "2.1", "number": npi}, timeout=timeout)
    resp.raise_for_status()
    results = resp.json().get("results") or []
    if not results:
        return None
    record = results[0]
    basic = record.get("basic", {})
    if record.get("enumeration_type") == "NPI-2":
        name = basic.get("organization_name") or ""
        return NppesRecord(npi, name, None, None, "NPI-2")
    first, last = basic.get("first_name"), basic.get("last_name")
    return NppesRecord(npi, f"{first or ''} {last or ''}".strip(), first, last, "NPI-1")
