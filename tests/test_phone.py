import pytest

from resume_screener.phone import normalize_phone


@pytest.mark.parametrize("raw, expected", [
    ("090000 00101", "+919000000101"),          # leading zero, a space
    ("7000000102", "+917000000102"),            # bare ten digits
    ("0091-9000000103", "+919000000103"),       # 0091 prefix
    ("+91 80000 00104", "+918000000104"),       # +91 and spaces
    ("91 9000000105", "+919000000105"),         # 91 without the plus
    ("(020) 2567 0000 / 9000000106", "+919000000106"),  # landline first, mobile second
])
def test_formats_that_appear_on_real_resumes(raw, expected):
    assert normalize_phone(raw) == (expected, "")


@pytest.mark.parametrize("raw", ["", None, "12345", "5000000101", "020 2567 0000"])
def test_refuses_rather_than_guesses(raw):
    phone, reason = normalize_phone(raw)
    assert phone == ""
    assert reason  # always says why, so the roster can show it
