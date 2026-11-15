import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def job():
    return json.loads((ROOT / "examples" / "job.example.json").read_text(encoding="utf-8"))


def canned_facts(name: str) -> dict:
    return json.loads((FIXTURES / "facts" / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def stub_extractor():
    """Stands in for the model: returns the known-right facts for whichever
    fixture resume is inside the prompt. Lets the whole pipeline run offline."""
    facts = {f.stem: json.loads(f.read_text(encoding="utf-8"))
             for f in (FIXTURES / "facts").glob("*.json")}

    def extract(prompt: str) -> dict:
        for data in facts.values():
            if data["candidate_name"].upper() in prompt:
                return dict(data)
        raise AssertionError("prompt did not contain a known fixture resume")

    return extract
