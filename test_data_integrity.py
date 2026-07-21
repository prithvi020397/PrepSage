"""Data integrity checks that would have caught QA regressions before deploy.
Verifies JSON structure, cross-references, and basic route smoke tests."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

DATA_FILES = {
    "questions.json": {"type": list, "min_length": 1},
    "solutions.json": {"type": dict, "min_length": 1},
    "concept_maps.json": {"type": dict, "min_length": 1},
    "traces.json": {"type": dict, "min_length": 1},
}

DESIGN_LANGS = {"design", "tradeoff", "decomposition"}


def _load(name):
    with open(name) as f:
        return json.load(f)


class TestJsonIntegrity:
    def test_all_json_files_parse(self):
        for name in DATA_FILES:
            data = _load(name)
            spec = DATA_FILES[name]
            assert isinstance(data, spec["type"]), f"{name}: expected {spec['type']}"
            assert len(data) >= spec["min_length"], f"{name}: too short"

    def test_questions_have_ids(self):
        questions = _load("questions.json")
        ids = set()
        for q in questions:
            assert "id" in q, f"question missing id: {q.get('title', '?')[:40]}"
            assert q["id"] not in ids, f"duplicate question id: {q['id']}"
            ids.add(q["id"])
        assert len(ids) == len(questions)

    def test_solutions_cross_reference(self):
        questions = _load("questions.json")
        solutions = _load("solutions.json")
        qids = {q["id"] for q in questions}
        for sid in solutions:
            assert sid in qids, f"solution key {sid} has no matching question"
        coding_without = [
            q["id"] for q in questions
            if q["id"] not in solutions
            and q.get("lang") not in DESIGN_LANGS
        ]
        assert not coding_without, (
            f"coding questions without solutions: {coding_without[:10]}"
        )

    def test_concept_maps_aligned(self):
        questions = _load("questions.json")
        maps = _load("concept_maps.json")
        qids = {q["id"] for q in questions}
        for mid in maps:
            assert mid in qids, f"concept_map key {mid} has no matching question"

    def test_traces_aligned(self):
        questions = _load("questions.json")
        traces = _load("traces.json")
        qids = {q["id"] for q in questions}
        for tid in traces:
            assert tid in qids, f"trace key {tid} has no matching question"

    def test_questions_have_concepts(self):
        questions = _load("questions.json")
        missing = [
            q["id"] for q in questions
            if q.get("lang") not in DESIGN_LANGS
            and ("concept" not in q or not q["concept"])
        ]
        assert not missing, (
            f"coding questions missing concept: {missing[:10]}"
        )


_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    os.environ["LEGACY_MODE"] = "1"
    os.environ["OPENROUTER_API_KEY"] = "x"
    os.environ["DEEPGRAM_API_KEY"] = "x"
    import app as _
    _client = _.app.test_client()
    return _client


class TestRouteSmoke:
    def test_api_me_returns_200(self):
        c = _get_client()
        resp = c.get("/api/me")
        assert resp.status_code == 200, f"/api/me returned {resp.status_code}"

    def test_dashboard_renders(self):
        c = _get_client()
        resp = c.get("/dashboard")
        assert resp.status_code in (200, 302), f"/dashboard returned {resp.status_code}"
        if resp.status_code == 200:
            html = resp.get_data(as_text=True)
            assert "topbar" in html or "dashboard" in html.lower()

    def test_root_redirects(self):
        c = _get_client()
        resp = c.get("/")
        assert resp.status_code in (200, 302), f"/ returned {resp.status_code}"
