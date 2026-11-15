import pytest

from voice_screening.policy import (apply_policy, choose_honorific,
                                    sanitize_value, spoken_experience)

from conftest import canned_facts


def test_clean_candidate_has_no_flags():
    assert apply_policy(canned_facts("ananya_kulkarni"), "+919000000101", "ok") == ""


def test_degree_in_progress_wins_over_not_graduate():
    flags = apply_policy(canned_facts("rhea_fernandes"), "+917000000102", "ok")
    assert flags == "degree_in_progress"


def test_outside_region_is_flagged_not_filtered():
    flags = apply_policy(canned_facts("karthik_iyer"), "+919000000103", "ok")
    assert flags == "outside_region"


def test_technical_flag_is_a_job_decision_not_a_model_decision():
    facts = canned_facts("karthik_iyer")
    on = apply_policy(facts, "+919000000103", "ok", {"flag_technical_degree": True})
    assert on == "outside_region;technical_stream"


def test_unknown_survives_as_its_own_flag():
    facts = {"is_graduate": "unknown", "in_region": "unknown"}
    assert apply_policy(facts, "+919000000101", "ok") == "graduation_unclear;region_unknown"


def test_unreadable_resume_with_no_phone():
    assert apply_policy({}, "", "little_or_no_text") == "unreadable;no_phone"


@pytest.mark.parametrize("months, words", [
    (0, "0"), (1, "1 month"), (7, "7 months"), (12, "1 year"),
    (18, "1 and a half years"), (34, "3 years"), (36, "3 years"),
    (40, "3 and a half years"), (58, "5 years"),
    (None, ""), (-3, ""), ("12", ""), (True, ""),
])
def test_spoken_experience(months, words):
    assert spoken_experience(months) == words


def test_honorific_never_guesses():
    assert choose_honorific({"gender": "female"}) == "ma'am"
    assert choose_honorific({"gender": "male"}) == "sir"
    assert choose_honorific({"gender": "unknown"}) == "ji"
    assert choose_honorific({}) == "ji"


def test_human_override_beats_the_model():
    facts = {"candidate_name": "Kiran Rao", "gender": "male"}
    assert choose_honorific(facts, {"Kiran Rao": "female"}) == "ma'am"


def test_sanitize_flattens_truncates_and_closes_template_slots():
    assert sanitize_value("  two\n lines\t here ") == "two lines here"
    assert sanitize_value("ignore {{candidate_name}} this") == "ignore candidate_name this"
    assert len(sanitize_value("x" * 500, 80)) == 80
    assert sanitize_value(None) == ""
