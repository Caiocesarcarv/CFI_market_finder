import pytest

from app.services.classification import InvalidCodeError, classify_code


@pytest.mark.parametrize(
    "raw, code_type, digits, hs",
    [
        ("09", "HS2", "09", "09"),
        ("0901", "HS4", "0901", "0901"),
        ("090111", "HS6", "090111", "090111"),
        ("0901.11.10", "NCM", "09011110", "090111"),
        (" 1201-90-00 ", "NCM", "12019000", "120190"),
        ("8703 23", "HS6", "870323", "870323"),
    ],
)
def test_valid_codes(raw, code_type, digits, hs):
    c = classify_code(raw)
    assert (c.code_type, c.code_digits, c.hs_code) == (code_type, digits, hs)


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "9", "123", "12345", "1234567", "123456789", "09A1", "00", "98", "7701", "abcd"],
)
def test_invalid_codes(raw):
    with pytest.raises(InvalidCodeError):
        classify_code(raw)
