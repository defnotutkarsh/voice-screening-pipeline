"""A forgiving adapter for a plain JSON webhook.

Accepts the field names documented in the README, plus the common variations:
an id called `call_id` or `id`, and contexts that arrive as JSON *strings*
rather than objects (webhook templating systems often json.dumps a dict into a
slot, so the receiver gets a string of JSON).
"""
import json


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first(payload: dict, *names, default=""):
    for n in names:
        if payload.get(n) not in (None, ""):
            return payload[n]
    return default


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class GenericAdapter:
    def normalize(self, payload: dict) -> dict:
        return {
            "run_id": str(_first(payload, "run_id", "call_id", "id", default="unknown")),
            "call_time": str(_first(payload, "call_time", "started_at", "created_at")),
            "duration_seconds": _as_float(_first(payload, "duration_seconds", "duration")),
            "disposition": str(_first(payload, "disposition", "call_disposition", "status")),
            "transcript": str(_first(payload, "transcript")),
            "transcript_url": str(_first(payload, "transcript_url")),
            "recording_url": str(_first(payload, "recording_url")),
            "initial_context": _as_dict(_first(payload, "initial_context", "initial_context_json")),
            "gathered_context": _as_dict(_first(payload, "gathered_context",
                                                "gathered_context_json")),
        }
