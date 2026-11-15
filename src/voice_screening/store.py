"""Call results on disk, and the two CSVs derived from them.

    <out>/results/<run_id>.raw.json   the payload exactly as it arrived
    <out>/results/<run_id>.json       the normalised record, one per call
    <out>/results/<run_id>.txt        the transcript
    <out>/results.csv                 one row per call, for a recruiter to read
    <out>/retry_campaign.csv          everyone still to be reached, upload-ready

Both CSVs are REBUILT from the .json files on every delivery, never appended
to. Webhook senders retry a delivery that does not answer 2xx, so the same
call can arrive more than once; appending would give one candidate two rows
and no way to tell which is current. Rebuilding makes a redelivery a no-op.
"""
import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from .adapters import Adapter, GenericAdapter
from .config import results_config
from .retry import decide_retry

FETCH_TIMEOUT = 30
SHORT_DROP_VALUE = "short_drop"
# Facts about the CALL survive the short-call gate; they drive the redial list.
CALL_FACT_FIELDS = ("call_outcome", "callback_time_stated")


def safe_id(run_id) -> str:
    """A run id becomes a filename, and it arrives from the network."""
    s = re.sub(r"[^A-Za-z0-9_-]", "_", str(run_id))[:80].strip("_")
    return s or "unknown"


class ResultsStore:
    def __init__(self, out_dir: Path, job: dict | None = None,
                 adapter: Adapter | None = None, transcript_hosts=(), log=print):
        self.out = Path(out_dir)
        self.results = self.out / "results"
        self.csv_path = self.out / "results.csv"
        self.retry_path = self.out / "retry_campaign.csv"
        self.source_campaign = self.out / "LATEST_campaign.csv"
        self.cfg = results_config(job)
        self.adapter = adapter or GenericAdapter()
        self.transcript_hosts = {h.strip().lower() for h in transcript_hosts if h.strip()}
        self.log = log
        self.results.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------- writing

    def ingest(self, payload: dict, source: str = "webhook", skip_existing: bool = False):
        """Save one call. Returns the stored record, or None if it was skipped."""
        try:
            rec = self.adapter.normalize(payload)
        except Exception:
            rec = None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        rid = safe_id(rec["run_id"]) if rec else "unknown"
        if rid == "unknown":  # never let two id-less calls overwrite each other
            rid = f"unknown-{stamp}"

        if skip_existing and (self.results / f"{rid}.json").exists():
            return None

        # Written first and never touched again: whatever fails below, the one
        # thing that cannot be fetched a second time is already durable.
        (self.results / f"{rid}.raw.json").write_text(
            json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
        if rec is None:
            raise ValueError("payload could not be normalised; raw copy kept")

        rec["run_id"] = rid
        status, fname = self._save_transcript(rec, rid)
        rec.pop("transcript", None)  # lives in the .txt, not twice
        rec.update({
            "received_at": datetime.now().astimezone().isoformat(),
            "source": source,
            "transcript_status": status,
            "transcript_file": fname,
        })
        self._write_record(rid, rec)
        return rec

    def _write_record(self, rid: str, rec: dict) -> None:
        (self.results / f"{rid}.json").write_text(
            json.dumps(rec, indent=1, ensure_ascii=False), encoding="utf-8")

    def _save_transcript(self, rec: dict, rid: str) -> tuple[str, str]:
        name = f"{rid}.txt"
        if rec.get("transcript"):
            (self.results / name).write_text(rec["transcript"], encoding="utf-8")
            return "ok", name
        url = rec.get("transcript_url")
        if not url:
            return "no_url", ""
        # The URL comes from the network. Fetching whatever it says would let
        # anyone who can reach this server make it call internal addresses
        # (SSRF), so only hosts the operator listed are ever contacted.
        host = (urlparse(url).hostname or "").lower()
        if host not in self.transcript_hosts:
            return "host_not_allowed", ""
        try:
            r = requests.get(url, timeout=FETCH_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            self.log(f"  WARN transcript fetch failed for run {rid}: {type(e).__name__}")
            return f"fetch_failed: {type(e).__name__}", ""
        r.encoding = r.encoding or "utf-8"
        (self.results / name).write_text(r.text, encoding="utf-8")
        return "ok", name

    def refetch(self) -> int:
        """Retry every transcript that did not download. Returns how many it fixed."""
        fixed = 0
        for f in self._record_files():
            rec = json.loads(f.read_text(encoding="utf-8"))
            if rec.get("transcript_status") == "ok":
                continue
            status, fname = self._save_transcript(rec, f.stem)
            rec["transcript_status"], rec["transcript_file"] = status, fname
            self._write_record(f.stem, rec)
            fixed += status == "ok"
        return fixed

    # ------------------------------------------------------------- reading

    def _record_files(self):
        return [f for f in sorted(self.results.glob("*.json"))
                if not f.name.endswith(".raw.json")]

    def load_records(self) -> list:
        """Every saved call, oldest first, with the retry decision already made."""
        recs = []
        for f in self._record_files():
            try:
                rec = json.loads(f.read_text(encoding="utf-8"))
            except ValueError:
                self.log(f"  WARN skipping unreadable {f.name}")
                continue
            ic = rec.get("initial_context") or {}
            rec["_phone"] = ic.get("phone_number") or ""
            rec["_order"] = (str(rec.get("call_time") or rec.get("received_at") or ""),
                             str(rec.get("run_id", "")))
            rec["_retry"], rec["_retry_reason"] = decide_retry(rec)
            recs.append(rec)
        recs.sort(key=lambda r: r["_order"])
        return recs

    # ------------------------------------------------------------ results.csv

    def columns(self) -> list:
        parts = list(self.cfg["score_parts"])
        cols = ["run_id", "call_time", "phone_number", "candidate_name", "recommend"]
        if parts:
            cols += ["score_total"] + parts
        cols += [c for c in self.cfg["rubric_columns"] if c not in cols]
        cols += ["resume_qualification", "resume_stream", "resume_experience",
                 "call_outcome", "callback_time_stated", "retry", "retry_reason",
                 "call_disposition", "duration_seconds", "scoring_gate",
                 "transcript_file", "transcript_status"]
        return cols

    def rebuild_results_csv(self, records: list) -> int:
        cols, parts = self.columns(), self.cfg["score_parts"]
        cap = int(self.cfg["score_part_max"])
        rows = []
        for rec in records:
            ic = rec.get("initial_context") or {}
            gc = dict(rec.get("gathered_context") or {})
            try:
                dur = float(rec.get("duration_seconds") or 0)
            except (TypeError, ValueError):
                dur = 0.0

            if dur >= self.cfg["min_scored_duration_seconds"]:
                gate = "scored"
                if parts and any(gc.get(k) not in (None, "") for k in parts):
                    # Recounted from the parts, so an arithmetic slip by the
                    # model that filled the rubric never reaches the CSV.
                    total = 0
                    for k in parts:
                        try:
                            total += max(0, min(cap, int(float(gc.get(k)))))
                        except (TypeError, ValueError):
                            pass
                    gc["score_total"] = total
            else:
                # A 10-second call with a silent candidate can still come back
                # "shortlist": an extractor asked to fill a rubric fills it.
                # Below the floor, the rubric is discarded rather than trusted.
                gate = "short_call" if dur > 0 else "not_connected"
                gc = {k: v for k, v in gc.items() if k in CALL_FACT_FIELDS}
                gc["recommend"] = SHORT_DROP_VALUE

            row = {
                "run_id": rec.get("run_id", ""),
                "call_time": rec.get("call_time", ""),
                "phone_number": rec["_phone"],
                "candidate_name": ic.get("candidate_name", ""),
                # From the resume, not the call: the CSV row is the better copy
                # of anything the call only confirmed.
                "resume_qualification": ic.get("resume_qualification", ""),
                "resume_stream": ic.get("resume_stream", ""),
                "resume_experience": ic.get("resume_experience", ""),
                "retry": "yes" if rec["_retry"] else "no",
                "retry_reason": rec["_retry_reason"],
                "call_disposition": rec.get("disposition", ""),
                "duration_seconds": rec.get("duration_seconds", ""),
                "scoring_gate": gate,
                "transcript_file": rec.get("transcript_file", ""),
                "transcript_status": rec.get("transcript_status", ""),
            }
            for col in cols:
                row.setdefault(col, gc.get(col, ""))
            rows.append(row)

        with self.csv_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return len(rows)

    # ------------------------------------------------------ retry_campaign.csv

    def _campaign_columns(self) -> list:
        """The retry file reproduces the columns of the campaign file the calls
        came from, so it uploads straight back with no editing. A list hardcoded
        here would drift the first time the builder adds a column."""
        if self.source_campaign.exists():
            with self.source_campaign.open(encoding="utf-8", newline="") as fh:
                header = next(csv.reader(fh), None)
            if header:
                return header
        self.log(f"  WARN {self.source_campaign.name} missing - the retry file will carry "
                 f"phone_number only, so redials run without resume context")
        return ["phone_number"]

    def _campaign_rows_by_phone(self) -> dict:
        if not self.source_campaign.exists():
            return {}
        with self.source_campaign.open(encoding="utf-8", newline="") as fh:
            return {r.get("phone_number", ""): r for r in csv.DictReader(fh)}

    def rebuild_retry_csv(self, records: list) -> int:
        """Keyed by phone and decided on that phone's LATEST call, so a candidate
        reached on the second attempt drops off this file on their own."""
        latest = {}
        for rec in records:
            phone = rec["_phone"]
            if phone and (phone not in latest or rec["_order"] > latest[phone]["_order"]):
                latest[phone] = rec

        cols = self._campaign_columns()
        current = self._campaign_rows_by_phone()
        rows, filled = [], 0
        for phone, rec in sorted(latest.items()):
            if not rec["_retry"]:
                continue
            ic = rec.get("initial_context") or {}
            src = current.get(phone, {})
            row = {}
            for c in cols:
                v = ic.get(c, "")
                # A call's initial_context is a snapshot of what THAT call was
                # given. A column added to the campaign file afterwards is blank
                # in it forever - and blank is not visibly wrong. So the current
                # campaign file fills blanks, and only blanks: a value the call
                # actually carried is the historical truth about that call.
                if not v and src.get(c):
                    v, filled = src[c], filled + 1
                row[c] = v
            if "phone_number" in cols:
                row["phone_number"] = phone
            rows.append(row)
        if filled:
            self.log(f"  filled {filled} blank field(s) from {self.source_campaign.name}")

        with self.retry_path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        return len(rows)

    def rebuild_all(self) -> tuple[int, int]:
        """Rewrite both files. Returns (calls recorded, numbers still to reach)."""
        records = self.load_records()
        return self.rebuild_results_csv(records), self.rebuild_retry_csv(records)

    # --------------------------------------------------------------- backfill

    def backfill(self, payloads) -> tuple[int, int]:
        """Import calls from an export instead of waiting for a webhook.

        A push-only pipeline has one moment where a whole batch drops silently:
        the webhook fires while nothing is listening, is retried, then given up
        on. The platform still has every call, so there must be a pull path
        too. Calls already on disk are skipped, so this is safe to re-run and
        safe to run while the server is also receiving.
        """
        added = skipped = 0
        for payload in payloads:
            if self.ingest(payload, source="backfill", skip_existing=True) is None:
                skipped += 1
            else:
                added += 1
        self.rebuild_all()
        return added, skipped
