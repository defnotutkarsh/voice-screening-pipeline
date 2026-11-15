"""The one interface between this project and a voice platform.

Every platform (hosted or self-run) describes a finished call a little
differently. The results code does not care: it only reads the normalised
record below. Supporting a new platform means writing one `normalize` function.

Normalised call record (a plain dict):

    run_id            str   unique id of the call
    call_time         str   ISO timestamp of the call, "" if unknown
    duration_seconds  float seconds the call was connected, 0 if it never was
    disposition       str   the platform's own status word, e.g. "voicemail"
    transcript        str   transcript text, if the payload carried it inline
    transcript_url    str   where to download it, if it did not
    recording_url     str   optional
    initial_context   dict  what the call was GIVEN (the campaign CSV row)
    gathered_context  dict  what the call PRODUCED (outcome, rubric scores...)
"""
from typing import Protocol

CALL_RECORD_FIELDS = (
    "run_id", "call_time", "duration_seconds", "disposition", "transcript",
    "transcript_url", "recording_url", "initial_context", "gathered_context",
)


class Adapter(Protocol):
    def normalize(self, payload: dict) -> dict:
        """Turn one raw webhook/export payload into a normalised call record."""
        ...
