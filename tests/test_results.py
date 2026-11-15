"""The results path: webhook in, files on disk, two CSVs rebuilt."""
import csv
import json

import pytest
from fastapi.testclient import TestClient

from voice_screening.retry import decide_retry
from voice_screening.server import create_app
from voice_screening.store import ResultsStore, safe_id

from conftest import ROOT

CAMPAIGN = ("phone_number,candidate_name,honorific,probe_line\n"
            "+919000000101,Ananya Kulkarni,ma'am,Trained 6 new floor staff\n"
            "+918000000104,Imran Shaikh,sir,Achieve monthly target of 20 activations\n")


def payload(run_id, phone, outcome, duration=300, call_time="2026-11-15T10:00:00+05:30", **gc):
    return {
        "run_id": run_id, "call_time": call_time, "duration_seconds": duration,
        "disposition": "completed", "transcript": "agent: hello\ncandidate: hi",
        "initial_context": {"phone_number": phone, "candidate_name": "Test Person"},
        "gathered_context": {"call_outcome": outcome, **gc},
    }


@pytest.fixture
def store(tmp_path, job):
    (tmp_path / "LATEST_campaign.csv").write_text(CAMPAIGN, encoding="utf-8")
    return ResultsStore(tmp_path, job, log=lambda *_: None)


@pytest.fixture
def client(store):
    return TestClient(create_app(store))


def rows(path):
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def test_webhook_lands_on_disk(client, store):
    r = client.post("/post-call", json=payload("r1", "+919000000101", "completed"))
    assert r.status_code == 200 and r.json()["ok"] is True
    assert (store.results / "r1.raw.json").exists()
    assert (store.results / "r1.json").exists()
    assert (store.results / "r1.txt").read_text(encoding="utf-8").startswith("agent: hello")
    assert len(rows(store.csv_path)) == 1


def test_redelivery_is_a_no_op(client, store):
    for _ in range(3):  # a sender that retries delivers the same call again
        client.post("/post-call", json=payload("r1", "+919000000101", "completed"))
    assert len(rows(store.csv_path)) == 1


def test_a_call_that_did_not_happen_is_not_a_rejection(client, store):
    client.post("/post-call", json=payload("r1", "+919000000101", "voicemail", duration=8))
    client.post("/post-call", json=payload("r2", "+918000000104", "not_interested"))
    retry = rows(store.retry_path)
    assert [r["phone_number"] for r in retry] == ["+919000000101"]


def test_reached_on_second_attempt_drops_off_the_retry_list(client, store):
    client.post("/post-call", json=payload("r1", "+919000000101", "busy_callback",
                                           call_time="2026-11-15T10:00:00+05:30"))
    assert len(rows(store.retry_path)) == 1
    client.post("/post-call", json=payload("r2", "+919000000101", "completed",
                                           call_time="2026-11-15T16:00:00+05:30"))
    assert rows(store.retry_path) == []


def test_retry_file_has_the_campaign_shape_and_fills_blanks(client, store):
    client.post("/post-call", json=payload("r1", "+919000000101", "voicemail", duration=5))
    retry = rows(store.retry_path)[0]
    assert list(retry) == ["phone_number", "candidate_name", "honorific", "probe_line"]
    assert retry["candidate_name"] == "Test Person"   # what the call carried is kept
    assert retry["honorific"] == "ma'am"              # a blank is filled from the campaign file


def test_short_calls_are_not_scored(client, store):
    client.post("/post-call", json=payload("r1", "+919000000101", "hung_up", duration=12,
                                           recommend="shortlist", clarity_score=2))
    row = rows(store.csv_path)[0]
    assert row["scoring_gate"] == "short_call"
    assert row["recommend"] == "short_drop"
    assert row["clarity_score"] == ""
    assert row["call_outcome"] == "hung_up"           # call facts survive the gate


def test_total_is_recounted_from_the_parts(client, store):
    client.post("/post-call", json=payload(
        "r1", "+919000000101", "completed", score_total=8,   # the model's arithmetic
        clarity_score=2, listening_score=1, problem_solving_score=9, empathy_score="x"))
    assert rows(store.csv_path)[0]["score_total"] == "5"     # 2 + 1 + (9 capped to 2) + 0


def test_contexts_arriving_as_json_strings(client, store):
    p = payload("r1", "+919000000101", "completed")
    p["initial_context_json"] = json.dumps(p.pop("initial_context"))
    p["gathered_context_json"] = json.dumps(p.pop("gathered_context"))
    client.post("/post-call", json=p)
    assert rows(store.csv_path)[0]["phone_number"] == "+919000000101"


def test_the_example_payload_in_the_readme_works(client, store):
    example = json.loads((ROOT / "examples" / "webhook_payload.example.json").read_text("utf-8"))
    assert client.post("/post-call", json=example).json()["ok"] is True
    row = rows(store.csv_path)[0]
    assert row["score_total"] == "7" and row["recommend"] == "shortlist"


def test_backfill_recovers_missed_webhooks_and_skips_known_calls(client, store):
    client.post("/post-call", json=payload("r1", "+919000000101", "completed"))
    added, skipped = store.backfill([payload("r1", "+919000000101", "completed"),
                                     payload("r2", "+918000000104", "voicemail", duration=0)])
    assert (added, skipped) == (1, 1)
    assert len(rows(store.csv_path)) == 2


def test_secret_is_enforced_when_set(store):
    c = TestClient(create_app(store, secret="s3cret"))
    p = payload("r1", "+919000000101", "completed")
    assert c.post("/post-call", json=p).status_code == 401
    assert c.post("/post-call", json=p, headers={"X-Webhook-Secret": "s3cret"}).status_code == 200


def test_transcript_urls_are_not_fetched_unless_the_host_is_allowed(client, store):
    p = payload("r1", "+919000000101", "completed")
    del p["transcript"]
    p["transcript_url"] = "http://169.254.169.254/latest/meta-data/"
    assert client.post("/post-call", json=p).json()["transcript"] == "host_not_allowed"


def test_run_id_cannot_escape_the_results_folder(client, store):
    client.post("/post-call", json=payload("../../etc/passwd", "+919000000101", "completed"))
    assert all(f.parent == store.results for f in store.results.iterdir())
    assert safe_id("../../etc/passwd") == "etc_passwd"


def test_bad_body_is_rejected(client):
    assert client.post("/post-call", content=b"not json").status_code == 400
    assert client.post("/post-call", json=[1, 2]).status_code == 400


@pytest.mark.parametrize("gathered, disposition, expected", [
    ({"call_outcome": "completed"}, "", (False, "")),
    ({"call_outcome": "do_not_call"}, "", (False, "")),
    ({"call_outcome": "busy_callback"}, "", (True, "busy_callback")),
    ({"call_outcome": "something_new"}, "", (True, "unknown_outcome:something_new")),
    ({}, "no_answer", (True, "no_rubric:no_answer")),
])
def test_decide_retry(gathered, disposition, expected):
    assert decide_retry({"gathered_context": gathered, "disposition": disposition}) == expected
