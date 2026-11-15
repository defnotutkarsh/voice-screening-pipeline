"""The whole build path, offline: fixture text -> real PDF -> pdftotext ->
stubbed model -> policy -> CSVs -> validator."""
import csv
import shutil

import pytest

from voice_screening.build import CAMPAIGN_COLUMNS, run_build
from voice_screening.testpdf import text_to_pdf
from voice_screening.validate import check

from conftest import FIXTURES, ROOT

pytestmark = pytest.mark.skipif(shutil.which("pdftotext") is None,
                                reason="needs poppler's pdftotext")


@pytest.fixture
def built(tmp_path, job, stub_extractor):
    resumes = tmp_path / "resumes"
    resumes.mkdir()
    for txt in (FIXTURES / "resumes").glob("*.txt"):
        text_to_pdf(txt.read_text(encoding="utf-8"), resumes / f"{txt.stem}.pdf")
    # One scanned-style PDF: almost no text, so nothing dialable can come out.
    text_to_pdf("scan", resumes / "zz_scanned.pdf")

    def extractor(prompt):
        if "KULKARNI" in prompt or "FERNANDES" in prompt or "IYER" in prompt or "SHAIKH" in prompt:
            return stub_extractor(prompt)
        return {}

    result = run_build(resumes, tmp_path / "out", job, extractor, model_tag="stub",
                       log=lambda *_: None)
    return tmp_path / "out", result


def _rows(path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_two_files_two_audiences(built):
    out, result = built
    campaign, roster = _rows(result.campaign_path), _rows(result.roster_path)
    assert result.dialable == len(campaign) == 4      # only rows with a phone
    assert result.total == len(roster) == 5           # everyone, incl. the unreadable one
    assert list(campaign[0]) == CAMPAIGN_COLUMNS
    assert "email" not in campaign[0] and "email" in roster[0]


def test_known_answers_come_out_right(built):
    _, result = built
    by_name = {r["candidate_name"]: r for r in _rows(result.campaign_path)}

    ananya = by_name["Ananya Kulkarni"]
    assert ananya["phone_number"] == "+919000000101"
    assert ananya["honorific"] == "ma'am"
    assert ananya["resume_experience"] == "3 years"
    assert ananya["paper_flags"] == ""

    assert by_name["Rhea Fernandes"]["paper_flags"] == "degree_in_progress"
    assert by_name["Karthik Iyer"]["phone_number"] == "+919000000103"
    assert by_name["Karthik Iyer"]["paper_flags"] == "outside_region"
    assert by_name["Imran Shaikh"]["resume_experience"] == "5 years"


def test_unreadable_pdf_is_kept_in_the_roster_and_out_of_the_dial_file(built):
    _, result = built
    scanned = [r for r in _rows(result.roster_path) if r["resume_file"] == "zz_scanned.pdf"][0]
    assert scanned["phone_number"] == ""
    assert "unreadable" in scanned["paper_flags"] and "no_phone" in scanned["paper_flags"]


def test_second_run_is_served_from_cache(built, tmp_path, job):
    out, _ = built

    def must_not_be_called(prompt):
        if "scan" in prompt and "KULKARNI" not in prompt:
            return {}
        raise AssertionError("model was called for a resume that should be cached")

    result = run_build(tmp_path / "resumes", out, job, must_not_be_called, model_tag="stub",
                       log=lambda *_: None)
    assert result.dialable == 4


def test_built_csv_passes_validation_against_the_example_prompt(built):
    _, result = built
    assert check(result.campaign_path, ROOT / "examples" / "prompts", log=lambda *_: None) == 0
