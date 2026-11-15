import pytest

from resume_screener.validate import check, template_columns


def _csv(tmp_path, text):
    p = tmp_path / "campaign.csv"
    p.write_text(text, encoding="utf-8")
    return p


def _prompts(tmp_path, text):
    d = tmp_path / "prompts"
    d.mkdir(exist_ok=True)
    (d / "call.txt").write_text(text, encoding="utf-8")
    return d


quiet = dict(log=lambda *_: None)


def test_good_file_passes(tmp_path):
    p = _csv(tmp_path, "phone_number,candidate_name\n+919000000101,Asha\n")
    assert check(p, **quiet) == 0


@pytest.mark.parametrize("body, why", [
    ("candidate_name\nAsha\n", "no phone column"),
    ("phone_number\n9000000101\n", "missing plus"),
    ("phone_number\n+91-90000-00101\n", "punctuation"),
    ("phone_number\n+919000000101\n+919000000101\n", "duplicate number"),
    ("phone_number\n", "no data rows"),
])
def test_bad_files_fail(tmp_path, body, why):
    assert check(_csv(tmp_path, body), **quiet) == 1, why


def test_template_variables_and_fallbacks_are_found(tmp_path):
    d = _prompts(tmp_path, "Hi {{candidate_name}}, {{ honorific | fallback:ji }}. "
                           "{{initial_context.probe_line}} {{gathered_context.score}}")
    assert template_columns(d) == {"candidate_name": None, "honorific": "ji", "probe_line": None}


def test_renamed_column_is_caught_before_the_call_not_during_it(tmp_path):
    """The prompt says {{probe_line}}; the CSV calls it probe. A dialler would
    accept this file, and every call would speak an empty sentence."""
    p = _csv(tmp_path, "phone_number,probe\n+919000000101,Trained six staff\n")
    assert check(p, _prompts(tmp_path, 'Ask about "{{probe_line}}"'), **quiet) == 1


def test_empty_cells_fail_only_when_the_prompt_has_no_fallback(tmp_path):
    p = _csv(tmp_path, "phone_number,honorific\n+919000000101,\n+917000000102,sir\n")
    assert check(p, _prompts(tmp_path, "{{honorific | fallback:ji}}"), **quiet) == 0
    assert check(p, _prompts(tmp_path, "{{honorific}}"), **quiet) == 1
