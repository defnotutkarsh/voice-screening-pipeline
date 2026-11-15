from datetime import date

from resume_screener.extract import RESPONSE_SCHEMA, build_prompt, cache_key


def test_prompt_carries_todays_date(job):
    """The model has no clock. If this line ever goes missing, every currently
    employed candidate's experience is measured against a date the model made
    up - and the result looks perfectly plausible."""
    prompt = build_prompt(job, "resume text", today=date(2026, 11, 15))
    assert "TODAY'S DATE IS 15 November 2026" in prompt


def test_prompt_describes_the_job_and_region_but_no_eligibility_rule(job):
    prompt = build_prompt(job, "resume text")
    assert job["role_title"] in prompt
    assert job["region"]["covers"] in prompt
    # Policy stays out of the prompt: the model reads, Python decides.
    assert "flag_technical_degree" not in prompt


def test_every_schema_field_is_required():
    assert set(RESPONSE_SCHEMA["required"]) == set(RESPONSE_SCHEMA["properties"])


def test_cache_key_changes_with_text_model_and_job(job):
    base = cache_key("text", "model-a", job)
    assert cache_key("text", "model-a", job) == base
    assert cache_key("other", "model-a", job) != base
    assert cache_key("text", "model-b", job) != base
    assert cache_key("text", "model-a", {**job, "role_title": "Other"}) != base
