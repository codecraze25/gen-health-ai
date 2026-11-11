from datetime import date

import pytest

from app import validation as v


@pytest.mark.parametrize("npi", ["1234567893", "1245319599", "1003000126"])
def test_valid_npis(npi):
    assert v.check_npi(npi) is None


@pytest.mark.parametrize(
    "npi", ["9182734556", "1234567890", "123456789", "12345678901", "abcdefghij"]
)
def test_invalid_npis(npi):
    assert v.check_npi(npi) is not None


def test_dob_rules():
    today = date(2026, 11, 11)
    assert v.check_dob(date(1980, 1, 1), today) is None
    assert v.check_dob(date(2027, 1, 1), today) is not None
    assert v.check_dob(date(1899, 12, 31), today) is not None
    assert v.dob_warning(date(1900, 12, 5), today) is not None
    assert v.dob_warning(date(1950, 12, 5), today) is None


@pytest.mark.parametrize(
    "name",
    ["Marie", "Curie", "O'Brien", "Mary-Jane", "Arjun Raj D.P.M", "José Núñez", "Smith, John"],
)
def test_valid_names(name):
    assert v.check_person_name(name) is None


@pytest.mark.parametrize("name", ["", "J0hn", "Robert'); DROP TABLE", "<script>", "a" * 101])
def test_invalid_names(name):
    assert v.check_person_name(name) is not None
