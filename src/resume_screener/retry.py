"""Who still has to be reached. Policy, so it lives in Python where it can be
read and changed, not in a prompt.

The call's job is to say WHAT HAPPENED (`call_outcome`). Deciding what that
earns is this file.

A call that did not happen is not a rejection. Someone who was driving, a
brother who answered, and a number that rang to a recording have all NOT been
screened: dial them again. Someone not interested, someone who asked not to be
called, and a wrong number are finished. For that difference to exist in the
data, it first has to exist as separate endings in the agent's prompt.
"""

RETRY_OUTCOMES = {
    "busy_callback",     # the candidate asked for another time
    "unavailable_now",   # right number, could not come to the phone
    "voicemail",         # a recording answered
    "hung_up",           # line dropped before any screening answer
    "no_usable_data",    # connected, but nothing came back worth keeping
}
FINAL_OUTCOMES = {
    "completed",
    "knockout_fail",
    "wrong_person",
    "not_interested",
    "do_not_call",       # never dial this number again, on this batch or any other
}

# A dial that never connected, or hit voicemail, usually comes back with no
# rubric at all. Every one of those means the call did not happen.
NO_RUBRIC_IS_RETRY = True


def decide_retry(record: dict) -> tuple[bool, str]:
    """Should this number be dialled again? Returns (retry, reason).

    Unknown outcome words retry rather than drop: losing a candidate to a word
    nobody recognised is the expensive mistake here.
    """
    gathered = record.get("gathered_context") or {}
    outcome = str(gathered.get("call_outcome") or "").strip()
    if outcome in FINAL_OUTCOMES:
        return False, ""
    if outcome in RETRY_OUTCOMES:
        return True, outcome
    if outcome:
        return True, f"unknown_outcome:{outcome}"
    disposition = str(record.get("disposition") or "").strip() or "none"
    return NO_RUBRIC_IS_RETRY, f"no_rubric:{disposition}"
