"""Command line entry point:  voice-screening <command> ...

    build      resume PDFs -> campaign CSV + roster CSV
    validate   check a campaign CSV before uploading it to a dialler
    serve      receive post-call webhooks and keep results on disk
    backfill   import calls from a JSON/JSONL export (the pull path)
    rebuild    rebuild results.csv and retry_campaign.csv from saved calls
    refetch    retry transcript downloads that failed
    make-pdf   turn a text file into a test PDF
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv


def _log(msg):
    print(f"{datetime.now().strftime('%H:%M:%S')}  {msg}", flush=True)


def _store(args):
    from .config import load_job
    from .store import ResultsStore
    job = load_job(args.job) if args.job else None
    hosts = os.getenv("TRANSCRIPT_HOSTS", "").split(",")
    return ResultsStore(Path(args.out), job, transcript_hosts=hosts, log=_log)


def cmd_build(args):
    from .build import run_build
    from .config import load_job
    from .llm import extractor_from_env
    extractor = None if args.text_only else extractor_from_env(args.model)
    run_build(Path(args.resumes), Path(args.out), load_job(args.job), extractor,
              model_tag=getattr(extractor, "model", ""), limit=args.limit,
              use_cache=not args.no_cache, text_only=args.text_only)


def cmd_validate(args):
    from .validate import check
    files = args.csv or sorted(str(p) for p in Path(args.out).glob("campaign_*.csv"))[-1:]
    if not files:
        sys.exit(f"no CSV given and no campaign_*.csv in {args.out}/")
    prompts = Path(args.prompts) if args.prompts else None
    sys.exit(max(check(Path(f), prompts) for f in files))


def cmd_serve(args):
    import uvicorn
    from .server import create_app
    store = _store(args)
    secret = os.getenv("WEBHOOK_SECRET") or None
    _log(f"listening on http://{args.host}:{args.port}/post-call"
         + ("" if secret else "   (no WEBHOOK_SECRET set: anyone who can reach this port can post)"))
    _log(f"results -> {store.csv_path}")
    _log(f"redial  -> {store.retry_path}")
    uvicorn.run(create_app(store, secret), host=args.host, port=args.port, log_level="warning")


def _read_export(path: Path):
    """A JSON array of payloads, or JSONL (one payload per line)."""
    text = path.read_text(encoding="utf-8").strip()
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def cmd_backfill(args):
    store = _store(args)
    added, skipped = store.backfill(_read_export(Path(args.export)))
    _log(f"backfill: {added} imported, {skipped} already on disk")


def cmd_rebuild(args):
    n_done, n_retry = _store(args).rebuild_all()
    _log(f"{n_done} calls in results.csv, {n_retry} still to reach in retry_campaign.csv")


def cmd_refetch(args):
    store = _store(args)
    fixed = store.refetch()
    n_done, n_retry = store.rebuild_all()
    _log(f"refetch: {fixed} recovered, {n_done} calls, {n_retry} still to reach")


def cmd_make_pdf(args):
    from .testpdf import text_to_pdf
    dst = text_to_pdf(Path(args.src).read_text(encoding="utf-8"), Path(args.dst))
    print(f"wrote {dst} ({dst.stat().st_size} bytes)")


def main(argv=None):
    load_dotenv()
    ap = argparse.ArgumentParser(prog="voice-screening", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def add_out(p):
        p.add_argument("--out", default="out", help="output folder (default: ./out)")

    def add_job(p, required=False):
        p.add_argument("--job", required=required, default=None if required else None,
                       help="path to the job JSON (see examples/job.example.json)")

    p = sub.add_parser("build", help="resume PDFs -> campaign CSV + roster CSV")
    add_job(p, required=True)
    add_out(p)
    p.add_argument("--resumes", default="resumes", help="folder of PDFs (default: ./resumes)")
    p.add_argument("--model", default=None, help="override GEMINI_MODEL")
    p.add_argument("--limit", type=int, default=0, help="only the first N files")
    p.add_argument("--text-only", action="store_true",
                   help="extract text and stop; makes no API calls and costs nothing")
    p.add_argument("--no-cache", action="store_true", help="force a re-parse")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("validate", help="check a campaign CSV before upload")
    p.add_argument("csv", nargs="*", help="CSV file(s); default: newest campaign_*.csv in --out")
    add_out(p)
    p.add_argument("--prompts", help="folder of prompt files to check column coverage against")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("serve", help="receive post-call webhooks")
    add_job(p)
    add_out(p)
    # Loopback by default: a server on 0.0.0.0 is reachable from the whole
    # network, which should be a choice, not an accident.
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8086)
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("backfill", help="import calls from a JSON/JSONL export")
    p.add_argument("export", help="file holding a JSON array, or one JSON payload per line")
    add_job(p)
    add_out(p)
    p.set_defaults(fn=cmd_backfill)

    p = sub.add_parser("rebuild", help="rebuild both CSVs from the saved calls")
    add_job(p)
    add_out(p)
    p.set_defaults(fn=cmd_rebuild)

    p = sub.add_parser("refetch", help="retry failed transcript downloads")
    add_job(p)
    add_out(p)
    p.set_defaults(fn=cmd_refetch)

    p = sub.add_parser("make-pdf", help="turn a text file into a test PDF")
    p.add_argument("src")
    p.add_argument("dst")
    p.set_defaults(fn=cmd_make_pdf)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
