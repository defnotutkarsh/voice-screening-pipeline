"""Resume PDFs -> two CSVs.

    PDF --pdftotext--> text --model--> facts JSON --python--> CSV row

Two files come out on purpose:

  * campaign_*.csv is the MACHINE contract: only dialable rows, only the
    columns the voice agent may see. Each column becomes a prompt variable.
  * roster_*.csv is the HUMAN one: every candidate, including the ones with no
    phone number, plus the fields the agent never sees.

Nothing here dials anyone. It only writes files.
"""
import csv
import json
import shutil
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .extract import build_prompt, cache_key
from .llm import Extractor
from .phone import normalize_phone
from .policy import (MAX_PROBE_LINE, apply_policy, choose_honorific,
                     load_gender_overrides, sanitize_value, spoken_experience)
from .textlayer import clean_text, parse_status, pdf_to_text

# `phone_number` is the only column a dialler needs; it must start with '+'.
# Every other column is context for the agent's prompt.
CAMPAIGN_COLUMNS = [
    "phone_number",
    "candidate_name",
    "candidate_name_spoken",
    "honorific",
    "resume_qualification",
    "resume_stream",
    "resume_grad_year",
    "resume_is_graduate",
    "resume_city",
    "resume_in_region",
    "resume_experience",
    "resume_current_role",
    "probe_topic",
    "probe_line",
    "paper_flags",
    "resume_file",
    "parsed_at",
]

ROSTER_EXTRA = ["gender", "gender_basis", "email", "phone_raw", "parse_status",
                "extraction_notes", "text_chars", "experience_months"]


@dataclass
class BuildResult:
    campaign_path: Path
    roster_path: Path
    dialable: int
    total: int
    flag_tally: Counter


def build_rows(pdf_name: str, facts: dict, status: str, text_chars: int,
               policy: dict | None = None, overrides: dict | None = None) -> tuple[dict, dict]:
    """One resume's facts -> (campaign row, roster row)."""
    phone, phone_reason = normalize_phone(facts.get("phone_raw", ""))
    exp_months = facts.get("experience_months")

    campaign = {
        "phone_number": phone,
        "candidate_name": sanitize_value(facts.get("candidate_name")),
        "candidate_name_spoken": sanitize_value(facts.get("candidate_name_spoken"), 40),
        "honorific": choose_honorific(facts, overrides),
        "resume_qualification": sanitize_value(facts.get("highest_qualification"), 40),
        "resume_stream": sanitize_value(facts.get("stream"), 40),
        "resume_grad_year": sanitize_value(facts.get("grad_year"), 10),
        "resume_is_graduate": facts.get("is_graduate", "unknown"),
        "resume_city": sanitize_value(facts.get("city")),
        "resume_in_region": facts.get("in_region", "unknown"),
        "resume_experience": spoken_experience(exp_months),
        "resume_current_role": sanitize_value(facts.get("current_role")),
        "probe_topic": sanitize_value(facts.get("probe_topic"), 60),
        "probe_line": sanitize_value(facts.get("probe_line"), MAX_PROBE_LINE),
        "paper_flags": apply_policy(facts, phone, status, policy),
        "resume_file": pdf_name,
        "parsed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    roster = dict(campaign)
    roster.update({
        "gender": facts.get("gender", "unknown"),
        "gender_basis": facts.get("gender_basis", "unknown"),
        "email": sanitize_value(facts.get("email"), 120),
        "phone_raw": sanitize_value(facts.get("phone_raw"), 40),
        "parse_status": status if phone else f"{status}; phone: {phone_reason}",
        "extraction_notes": sanitize_value(facts.get("extraction_notes"), 300),
        "text_chars": str(text_chars),
        "experience_months": exp_months if isinstance(exp_months, int) else "",
    })
    return campaign, roster


def _write_csv(path: Path, columns: list, rows: list) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        w.writerows(rows)


def _point_latest(link: Path, target: Path) -> None:
    link.unlink(missing_ok=True)
    try:
        link.symlink_to(target.name)
    except OSError:  # filesystems without symlinks
        shutil.copy2(target, link)


def run_build(resumes_dir: Path, out_dir: Path, job: dict, extractor: Extractor | None,
              model_tag: str = "", limit: int = 0, use_cache: bool = True,
              text_only: bool = False, log=print) -> BuildResult | None:
    """Parse every PDF in `resumes_dir` and write the two CSVs into `out_dir`."""
    pdfs = sorted(Path(resumes_dir).glob("*.pdf"))
    if limit:
        pdfs = pdfs[:limit]
    if not pdfs:
        sys.exit(f"No PDFs in {resumes_dir}")

    out_dir = Path(out_dir)
    cache_dir = out_dir / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    overrides = load_gender_overrides(out_dir)

    log(f"{len(pdfs)} resume(s) in {resumes_dir}")
    log(f"job: {job['company']} - {job['role_title']}\n")

    campaign_rows, roster_rows = [], []
    for i, pdf in enumerate(pdfs, 1):
        text = clean_text(pdf_to_text(pdf))
        status = parse_status(text)
        log(f"[{i}/{len(pdfs)}] {pdf.name}  {len(text)} chars  {status}")

        if text_only:
            log("      " + text[:160].replace("\n", " ") + "\n")
            continue
        if extractor is None:
            sys.exit("No extractor configured. Set GEMINI_API_KEY in .env "
                     "(or run with --text-only to check the PDFs first).")

        cache_file = cache_dir / f"{cache_key(text, model_tag, job)}.json"
        if use_cache and cache_file.exists():
            facts = json.loads(cache_file.read_text(encoding="utf-8"))
            log("      cached")
        else:
            try:
                facts = extractor(build_prompt(job, text))
                cache_file.write_text(json.dumps(facts, indent=1, ensure_ascii=False),
                                      encoding="utf-8")
            except Exception as e:  # one failed resume must not lose the batch
                print(f"      EXTRACTION FAILED: {e}", file=sys.stderr)
                facts, status = {}, "extraction_failed"

        c, r = build_rows(pdf.name, facts, status, len(text), job.get("policy"), overrides)
        campaign_rows.append(c)
        roster_rows.append(r)
        log(f"      {c['candidate_name'] or '(no name)'}  {c['phone_number'] or 'NO PHONE'}"
            f"  {c['resume_qualification'] or '?'}  flags={c['paper_flags'] or 'none'}")

    if text_only:
        return None

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dialable = [r for r in campaign_rows if r["phone_number"]]
    camp_path = out_dir / f"campaign_{stamp}.csv"
    roster_path = out_dir / f"roster_{stamp}.csv"
    _write_csv(camp_path, CAMPAIGN_COLUMNS, dialable)
    _write_csv(roster_path, CAMPAIGN_COLUMNS + ROSTER_EXTRA, roster_rows)
    _point_latest(out_dir / "LATEST_campaign.csv", camp_path)
    _point_latest(out_dir / "LATEST_roster.csv", roster_path)

    tally = Counter(f for r in campaign_rows for f in r["paper_flags"].split(";") if f)
    undialable = len(campaign_rows) - len(dialable)
    log(f"\ncampaign CSV  {camp_path}   {len(dialable)} dialable")
    log(f"roster CSV    {roster_path}   {len(roster_rows)} total"
        + (f", {undialable} with no usable phone" if undialable else ""))
    if tally:
        log("\npaper flags, recorded only, everyone with a number still gets dialled:")
        for k, v in tally.most_common():
            log(f"  {v:>3}  {k}")
    return BuildResult(camp_path, roster_path, len(dialable), len(roster_rows), tally)
