"""Load the job file: the one place a hiring team describes the role."""
import json
import sys
from pathlib import Path

REQUIRED = ("company", "role_title", "what_the_job_is", "region", "probe_relevance")

DEFAULT_RESULTS = {
    # Rubric fields the call produces that are scores, summed into score_total.
    "score_parts": [],
    "score_part_max": 2,
    # A call shorter than this cannot have produced a real assessment.
    "min_scored_duration_seconds": 60,
    # Other rubric fields worth a column in results.csv, in reading order.
    "rubric_columns": ["recommend_reason"],
}


def load_job(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        sys.exit(f"Job file not found: {path}  (start from examples/job.example.json)")
    job = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if k not in job]
    if missing:
        sys.exit(f"{path.name} is missing: {', '.join(missing)}")
    if not {"name", "covers"} <= set(job["region"]):
        sys.exit(f"{path.name}: 'region' needs both 'name' and 'covers'")
    return job


def results_config(job: dict | None) -> dict:
    cfg = dict(DEFAULT_RESULTS)
    cfg.update((job or {}).get("results") or {})
    return cfg
