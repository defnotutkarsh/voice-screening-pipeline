"""Everything that is a DECISION rather than a fact. Pure Python, no model.

Change the job's rules and you re-run this over cached facts; you never re-parse
a resume and never pay for the API twice.
"""
import csv
import re
import unicodedata
from pathlib import Path

# What the voice agent may be handed. Long free text on a call is unusable, and
# a long value is also the easiest place to hide an instruction.
MAX_FIELD = 80
MAX_PROBE_LINE = 220


def sanitize_value(s, limit: int = MAX_FIELD) -> str:
    """Flatten a model-supplied string before it reaches a prompt or a CSV.

    This stops mangling and truncation, NOT prompt injection. Resume text is
    written by the candidate, so a line can be shaped like an instruction. The
    agent's prompt has to treat these values as quoted data; no regex can do
    that from here.
    """
    if s is None:
        return ""
    s = unicodedata.normalize("NFC", str(s))
    s = "".join(ch for ch in s if ord(ch) >= 32)
    s = s.replace("{{", "").replace("}}", "")  # never let a value open a template slot
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > limit:
        s = s[: limit - 1].rstrip() + "…"
    return s


def apply_policy(facts: dict, phone: str, parse_status: str, policy: dict | None = None) -> str:
    """Derive paper flags from facts. Returns them joined with ';'.

    Flags are RECORDED, never acted on. Everyone with a phone number gets
    dialled; the call is the source of truth because a resume is a snapshot and
    people move, finish degrees and change their minds.
    """
    policy = policy or {}
    flags = []
    if parse_status != "ok":
        flags.append("unreadable")
    if not phone:
        flags.append("no_phone")
    if facts.get("degree_in_progress") == "true":
        flags.append("degree_in_progress")
    elif facts.get("is_graduate") == "false":
        flags.append("not_graduate")
    elif facts.get("is_graduate") == "unknown":
        flags.append("graduation_unclear")
    if facts.get("in_region") == "false":
        flags.append("outside_region")
    elif facts.get("in_region") == "unknown":
        flags.append("region_unknown")
    if policy.get("flag_technical_degree") and facts.get("is_technical_degree") == "true":
        flags.append("technical_stream")
    return ";".join(flags)


# What the agent actually says. A scripted prompt gets the finished word, never
# the gender: handing the model `gender=female` would make it do this mapping in
# its head at every place the word appears, and each one is a chance to drift.
HONORIFICS = {"male": "sir", "female": "ma'am"}

# Gender-neutral and ordinary in Indian speech, so an unknown never has to be
# guessed and never sounds like a hedge. This is why the tri-state survives
# extraction instead of being collapsed to a boolean.
HONORIFIC_UNKNOWN = "ji"


def load_gender_overrides(out_dir: Path) -> dict:
    """Hand-corrections from <out>/gender_overrides.csv (candidate_name,gender).

    A human edit is the last word on this field - above the resume and above
    the model - and it must survive every re-parse, or the override file is a
    half-truth.
    """
    f = Path(out_dir) / "gender_overrides.csv"
    if not f.exists():
        return {}
    with f.open(encoding="utf-8") as fh:
        return {r["candidate_name"]: r["gender"] for r in csv.DictReader(fh)
                if r.get("candidate_name") and r.get("gender")}


def choose_honorific(facts: dict, overrides: dict | None = None) -> str:
    gender = facts.get("gender")
    if overrides:
        gender = overrides.get(facts.get("candidate_name", ""), gender)
    return HONORIFICS.get(gender, HONORIFIC_UNKNOWN)


def spoken_experience(months) -> str:
    """Whole months -> words a voice agent can read aloud after "about".

    Under a year stays in months. A year or more rounds to the nearest half
    year, and the half is written out because "1.5" is read aloud as "one point
    five". Zero stays "0" so a prompt can branch on a fresher.
    """
    if not isinstance(months, int) or isinstance(months, bool) or months < 0:
        return ""
    if months == 0:
        return "0"
    if months < 12:
        return "1 month" if months == 1 else f"{months} months"
    years, half = divmod(round(months / 6), 2)
    if half:
        return f"{years} and a half years"
    return "1 year" if years == 1 else f"{years} years"
