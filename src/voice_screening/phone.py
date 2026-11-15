"""Phone normalisation. Deterministic on purpose.

Asking a language model to tidy a phone number puts a guess in the one field
that decides who actually gets dialled, and a plausible guess there rings a
stranger. So the model copies the number exactly as printed and this module
does the rest.

This is the one country-specific piece of the pipeline: it understands Indian
mobile numbers. Swap `normalize_phone` to support another numbering plan.
"""
import re


def normalize_phone(raw: str) -> tuple[str, str]:
    """Indian mobile -> +91XXXXXXXXXX. Returns (normalised, reason_if_failed)."""
    if not raw:
        return "", "no number on resume"

    # A resume often lists two numbers; take the first one that is valid.
    for chunk in re.split(r"[,;/|\n\r]+", str(raw)):
        digits = re.sub(r"\D", "", chunk)
        if digits.startswith("0091"):
            digits = digits[4:]
        elif digits.startswith("91") and len(digits) == 12:
            digits = digits[2:]
        elif digits.startswith("0") and len(digits) == 11:
            digits = digits[1:]
        if len(digits) == 10 and digits[0] in "6789":
            return "+91" + digits, ""

    # Fallback: the first 10-digit mobile pattern anywhere in the raw text.
    found = re.findall(r"(?:(?:\+?91|0)[\s-]?)?([6-9]\d{9})", str(raw))
    if found:
        return "+91" + found[0], ""

    all_digits = re.sub(r"\D", "", str(raw))
    return "", f"got {len(all_digits)} digits, need 10"
