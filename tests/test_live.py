"""Runs the real model against the fixture resumes. Skipped without a key.

    GEMINI_API_KEY=... pytest -m live

These are the fixtures whose right answers are already known, which is the
only way to catch the class of bug that produces plausible output instead of
an error (a wrong experience figure, a degree marked complete that is not).
"""
import os
from datetime import date

import pytest

from voice_screening.extract import build_prompt
from voice_screening.llm import extractor_from_env

from conftest import FIXTURES, canned_facts

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not os.getenv("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set"),
]

TODAY = date(2026, 11, 15)   # fixed, so the experience answers do not move
EXACT = ("in_region", "is_graduate", "degree_in_progress", "is_technical_degree", "phone_raw")


@pytest.mark.parametrize("name", ["ananya_kulkarni", "rhea_fernandes", "karthik_iyer",
                                  "imran_shaikh"])
def test_model_agrees_with_the_known_answers(job, name):
    text = (FIXTURES / "resumes" / f"{name}.txt").read_text(encoding="utf-8")
    got = extractor_from_env()(build_prompt(job, text, today=TODAY))
    want = canned_facts(name)
    for field in EXACT:
        assert got[field] == want[field], field
    assert abs(got["experience_months"] - want["experience_months"]) <= 2
    assert got["probe_line"] in text, "probe_line must be copied verbatim from the resume"
