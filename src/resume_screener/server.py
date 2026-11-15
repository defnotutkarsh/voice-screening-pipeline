"""The post-call webhook receiver.

    POST /post-call   one finished call, as JSON
    GET  /health
"""
import hmac

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .store import ResultsStore


def create_app(store: ResultsStore, secret: str | None = None) -> FastAPI:
    app = FastAPI(title="resume-screener results")

    @app.post("/post-call")
    async def post_call(request: Request):
        if secret:
            sent = request.headers.get("x-webhook-secret", "")
            # compare_digest takes the same time whether the first or the last
            # character is wrong, so the secret cannot be guessed by timing.
            if not hmac.compare_digest(sent, secret):
                return JSONResponse({"ok": False, "error": "bad secret"}, status_code=401)

        try:
            payload = await request.json()
            if not isinstance(payload, dict):
                raise ValueError("body is not a JSON object")
        except Exception as e:
            store.log(f"REJECTED unparseable body: {e}")
            return JSONResponse({"ok": False, "error": "body is not a JSON object"},
                                status_code=400)

        # From here on, always answer 200 once the payload is on disk. A
        # non-2xx makes the sender retry and eventually give up; a transcript
        # that would not download is not worth replaying the delivery for,
        # because `refetch` can pick it up later.
        try:
            rec = store.ingest(payload)
        except ValueError as e:
            store.log(f"KEPT RAW, could not normalise: {e}")
            return {"ok": False, "error": str(e)}

        n_done, n_retry = store.rebuild_all()
        outcome = (rec.get("gathered_context") or {}).get("call_outcome", "-")
        store.log(f"run {rec['run_id']}  outcome={outcome}  "
                  f"transcript={rec['transcript_status']}  "
                  f"({n_done} calls, {n_retry} still to reach)")
        return {"ok": True, "run_id": rec["run_id"], "transcript": rec["transcript_status"],
                "outcome": outcome, "still_to_reach": n_retry}

    @app.get("/health")
    async def health():
        return {"ok": True, "results": len(store.load_records())}

    return app
