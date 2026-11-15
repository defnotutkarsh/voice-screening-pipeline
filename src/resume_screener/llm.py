"""The model call, behind one small seam.

The rest of the pipeline only needs "a function that takes a prompt and returns
a facts dict". Anything with that shape works, which is also how the tests run
the whole pipeline without an API key. To use another provider, write one more
function like `GeminiExtractor.__call__` and pass it to `run_build`.
"""
import json
import os
from typing import Callable

import requests

Extractor = Callable[[str], dict]

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.8-flash"


class GeminiExtractor:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, schema: dict | None = None):
        from .extract import RESPONSE_SCHEMA
        self.api_key = api_key
        self.model = model
        self.schema = schema or RESPONSE_SCHEMA

    def __call__(self, prompt: str) -> dict:
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": self.schema,
                "temperature": 0,
            },
        }
        r = requests.post(
            GEMINI_URL.format(model=self.model),
            # Header, not a ?key= query string: URLs end up in logs and proxies.
            headers={"x-goog-api-key": self.api_key},
            json=body,
            timeout=120,
        )
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        try:
            text = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise RuntimeError(f"unexpected response shape: {json.dumps(data)[:300]}")
        return json.loads(text)


def extractor_from_env(model: str | None = None) -> GeminiExtractor | None:
    """Build the default extractor from GEMINI_API_KEY, or None if it is unset."""
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    return GeminiExtractor(key, model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL)
