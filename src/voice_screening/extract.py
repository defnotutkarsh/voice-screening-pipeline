"""The extraction contract: what the model is asked, and the shape it must answer in.

The model extracts FACTS ONLY. It is never told who is eligible, so it cannot
lean on a rule when a resume is ambiguous. Every decision is made later, in
plain Python (see policy.py).
"""
import hashlib
import json
from datetime import date

# Tri-state values are STRING enums on purpose. A JSON boolean has no room for
# "the resume does not say", and a missing key silently reads as false, which
# would fail people the resume never spoke about.
_TRI = {"type": "STRING", "enum": ["true", "false", "unknown"]}

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "candidate_name": {"type": "STRING"},
        "candidate_name_spoken": {"type": "STRING"},
        "phone_raw": {"type": "STRING"},
        "email": {"type": "STRING"},
        "city": {"type": "STRING"},
        "gender": {"type": "STRING", "enum": ["male", "female", "unknown"]},
        "gender_basis": {"type": "STRING", "enum": ["stated", "name", "unknown"]},
        "in_region": _TRI,
        "highest_qualification": {"type": "STRING"},
        "stream": {"type": "STRING"},
        "grad_year": {"type": "STRING"},
        "is_graduate": _TRI,
        "degree_in_progress": _TRI,
        "is_technical_degree": _TRI,
        "experience_months": {"type": "INTEGER"},
        "current_role": {"type": "STRING"},
        "probe_topic": {"type": "STRING"},
        "probe_line": {"type": "STRING"},
        "extraction_notes": {"type": "STRING"},
    },
}
RESPONSE_SCHEMA["required"] = list(RESPONSE_SCHEMA["properties"])


def build_prompt(job: dict, resume_text: str, today: date | None = None) -> str:
    # The model has no clock. Without this line "March 2024 - Present" gets
    # measured against whatever it assumes today is, and every currently
    # employed candidate's experience comes out wrong - plausibly wrong, with
    # no error anywhere.
    today_str = (today or date.today()).strftime("%d %B %Y")
    region = job["region"]
    script = job.get("spoken_name_script", "Devanagari")
    return f"""You are reading one job applicant's resume and pulling out facts for a
recruiter's calling sheet. You are not judging the candidate and you are not
deciding anything. Record only what the resume actually says.

TODAY'S DATE IS {today_str}. Use it for every date calculation and for deciding
whether a date is past or future. Never use any other assumption about today.

THE JOB THEY APPLIED TO
Company: {job['company']}. Role: {job['role_title']}.
{job['what_the_job_is']}

RULES FOR EVERY FIELD
Never infer, upgrade, or fill a gap with something plausible. If the resume does
not say it, leave the string empty or use unknown where the field allows it. A
blank field is a correct answer; an invented one corrupts a hiring decision.

candidate_name: their full name as printed.
candidate_name_spoken: just their FIRST name, written in {script} the way a local
  speaker would pronounce it. This is read aloud by a voice agent, so spell it
  for sound, not for etymology.
phone_raw: the phone number exactly as printed, with whatever spaces, plus signs,
  zeros or country code appear. Do not clean it up.
email: their email address as printed.
city: the city or locality of their address.
gender: male or female. This one field MAY be inferred from the first name when
  that name is unambiguous to a local speaker, because a voice agent has to
  address this person out loud and has no other source. Prefer what the document
  states. Answer unknown for a name you are not confident about, for a unisex
  name, and for a name whose usual gender you do not know. An honest unknown is
  handled gracefully by the caller; a confident wrong answer is said aloud to the
  candidate again and again.
gender_basis: stated if the resume itself says it anywhere - a gender field, a
  title such as Mr or Ms, son of or daughter of, or a pronoun used about
  themselves. name if you went by the first name alone. unknown if you answered
  unknown above.
in_region: true only if that address is inside {region['name']}, which covers
  {region['covers']}. false if the address is clearly elsewhere. unknown if
  there is no address at all.
highest_qualification: the highest qualification NAMED, whether finished or not.
stream: its subject or discipline.
grad_year: the year of that qualification if stated.
is_graduate: true only if a bachelors degree or higher is clearly COMPLETED. A
  degree described as ongoing, final year, appearing, result awaited, or with a
  paper or backlog pending is NOT completed. School qualifications alone are not.
degree_in_progress: true if a degree is named but not yet finished.
is_technical_degree: true if the highest degree is engineering, technology,
  computer applications or another technical discipline.
experience_months: total paid work experience in whole months. Internships and
  part time roles count. Count from the dates given; if a role says it is current,
  count it to today. 0 for someone with no paid work. Never guess a duration from
  a role that has no dates.
current_role: their present or most recent job title. Empty for a fresher.

CHOOSING THE PROBE, WHICH IS THE PART THAT MATTERS
A voice agent will ask this candidate one question built from their own resume,
to check that what is written actually happened. Pick the single line worth asking
about, by these rules and no others:
- It must describe something this person personally DID, not a skill they claim,
  not an objective, not a hobby, not a course they attended.
- It must carry a concrete detail. A number, a tool, a place, a named task.
- It must be answerable by them explaining how it actually worked, so that someone
  who only wrote it down would come apart on the follow up.
- Where several lines qualify, prefer relevance to this job: {job['probe_relevance']}
probe_line: that line copied VERBATIM from the resume. Never reword it.
probe_topic: a short neutral label for it, at most six words, no punctuation.
extraction_notes: anything that would mislead a recruiter reading this row alone.
  Contradictory dates, an ambiguous degree, a missing phone number. Empty if clean.

THE RESUME
<<<RESUME
{resume_text}
RESUME
"""


def cache_key(resume_text: str, model_tag: str, job: dict) -> str:
    """Content hash for the facts cache.

    The schema is part of the key because adding a field to it changes neither
    the resume, the model nor the job - so without it a cached entry comes back
    missing the new field, silently, and reads as absent forever.
    """
    blob = (resume_text + model_tag + json.dumps(job, sort_keys=True)
            + json.dumps(RESPONSE_SCHEMA, sort_keys=True))
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
