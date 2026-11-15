"""PDF -> clean plain text. No model involved."""
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

# pdftotext on a scanned PDF returns almost nothing rather than failing, so a
# length floor is the only way to tell "empty resume" from "photo of a resume".
MIN_USABLE_CHARS = 200


def pdf_to_text(pdf: Path) -> str:
    """Extract text with poppler's pdftotext. -layout keeps columns readable."""
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), "-"],
            capture_output=True, timeout=60,
        )
        return out.stdout.decode("utf-8", "replace")
    except FileNotFoundError:
        sys.exit("pdftotext not found. Install poppler "
                 "(Debian/Ubuntu: apt install poppler-utils, macOS: brew install poppler).")
    except Exception as e:  # a single bad file must not stop the batch
        print(f"    pdftotext failed on {pdf.name}: {e}", file=sys.stderr)
        return ""


def clean_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = "".join(ch for ch in s if ch in "\n\t" or ord(ch) >= 32)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def parse_status(text: str) -> str:
    return "ok" if len(text) >= MIN_USABLE_CHARS else "little_or_no_text"
