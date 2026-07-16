"""Tests for scoring logic — hire_verdict, split_wrap_up_reply, rubric_scores parsing."""
import json
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from app import hire_verdict, split_wrap_up_reply, CONCEPT_TAXONOMY, CONCEPT_TAXONOMY_AI


# ── hire_verdict ──────────────────────────────────────────────────────────

class TestHireVerdict(unittest.TestCase):
    def test_strong_hire_with_high_rubric(self):
        scores = {"phase1": 7, "phase2": 9, "phase3": 5, "phase4": 7, "phase5": 5, "phase6": 5}
        assert hire_verdict([], False, None, scores) == "Strong Hire"

    def test_hire_with_medium_rubric(self):
        # 23/44 = 52.27% → No Hire (needs ≥60%)
        scores = {"phase1": 5, "phase2": 6, "phase3": 3, "phase4": 5, "phase5": 3, "phase6": 1}
        assert hire_verdict([], False, None, scores) == "No Hire"
        # 27/44 = 61.36% → Hire
        scores = {"phase1": 5, "phase2": 6, "phase3": 3, "phase4": 5, "phase5": 3, "phase6": 5}
        assert hire_verdict([], False, None, scores) == "Hire"

    def test_no_hire_with_low_rubric(self):
        scores = {"phase1": 2, "phase2": 3, "phase3": 1, "phase4": 2, "phase5": 1, "phase6": 2}
        assert hire_verdict([], False, None, scores) == "No Hire"

    def test_strong_hire_boundary_85pct(self):
        # 37/44 = 84.09% — just under 85%
        scores = {"phase1": 8, "phase2": 10, "phase3": 6, "phase4": 8, "phase5": 5, "phase6": 0}
        assert hire_verdict([], False, None, scores) == "Hire"
        # 38/44 = 86.36% — just over 85%
        scores = {"phase1": 8, "phase2": 10, "phase3": 6, "phase4": 8, "phase5": 5, "phase6": 1}
        assert hire_verdict([], False, None, scores) == "Strong Hire"

    def test_hire_boundary_60pct(self):
        # 26/44 = 59.09% — just under 60%
        scores = {"phase1": 4, "phase2": 6, "phase3": 3, "phase4": 4, "phase5": 3, "phase6": 6}
        assert hire_verdict([], False, None, scores) == "No Hire"
        # 27/44 = 61.36% — just over 60%
        scores = {"phase1": 5, "phase2": 6, "phase3": 3, "phase4": 4, "phase5": 3, "phase6": 6}
        assert hire_verdict([], False, None, scores) == "Hire"

    def test_fallback_without_rubric_scores(self):
        # No rubric_scores — uses crude point heuristic
        # points = -len(missed) + (comm - 3) if comm else 0 - 2 if rushed
        assert hire_verdict([], False, 5, None) == "Strong Hire"  # 0 + 2 = 2
        assert hire_verdict([], False, 3, None) == "Strong Hire"  # 0 + 0 = 0
        assert hire_verdict([], False, 1, None) == "Hire"  # 0 + (-2) = -2

    def test_fallback_missed_concepts_penalize(self):
        # -1 + 0 = -1 → Hire
        assert hire_verdict(["idempotency_dedup"], False, 3, None) == "Hire"
        # -3 + 0 = -3 → Hire (boundary)
        assert hire_verdict(["a", "b", "c"], False, 3, None) == "Hire"
        # -4 + 0 = -4 → No Hire
        assert hire_verdict(["a", "b", "c", "d"], False, 3, None) == "No Hire"

    def test_fallback_rushed_penalizes(self):
        # rushed_to_design = True costs 2 points
        assert hire_verdict([], True, 3, None) == "Hire"
        assert hire_verdict([], True, 1, None) == "No Hire"

    def test_empty_rubric_scores_falls_back_to_heuristic(self):
        # {} is falsy → falls back to point heuristic, not rubric path
        # 0 missed concepts, no rush, no comm → points = 0 → Strong Hire
        scores = {}
        assert hire_verdict([], False, None, scores) == "Strong Hire"

    def test_partial_rubric_scores(self):
        # Only some phases present — missing phases count as 0
        scores = {"phase1": 8, "phase2": 10}
        # 18/44 = 40.9% → No Hire
        assert hire_verdict([], False, None, scores) == "No Hire"


# ── split_wrap_up_reply ───────────────────────────────────────────────────

class TestSplitWrapUpReply(unittest.TestCase):
    def test_plain_text_without_json(self):
        reply = "You did well on requirements but missed reliability."
        prose, concepts, rushed, score, note, rubric = split_wrap_up_reply(reply)
        assert prose == reply
        assert concepts == []
        assert rushed is False
        assert score is None
        assert note == ""
        assert rubric == {}

    def test_json_block_parsed(self):
        reply = """Good effort overall.

```json
{"missed_concepts": ["idempotency_dedup", "late_data_watermarks"], "rushed_to_design": true, "communication_score": 3, "communication_note": "Spoke clearly but jumped to design too fast.", "rubric_scores": {"phase1": 5, "phase2": 7, "phase3": 4, "phase4": 3, "phase5": 2, "phase6": 5}}
```"""
        prose, concepts, rushed, score, note, rubric = split_wrap_up_reply(reply)
        assert "Good effort" in prose
        assert "idempotency_dedup" in concepts
        assert "late_data_watermarks" in concepts
        assert rushed is True
        assert score == 3
        assert "jumped to design" in note
        assert rubric["phase1"] == 5
        assert rubric["phase4"] == 3

    def test_invalid_json_graceful_fallback(self):
        reply = """Some feedback.

```json
{invalid json here}
```"""
        prose, concepts, rushed, score, note, rubric = split_wrap_up_reply(reply)
        assert "Some feedback" in prose
        assert concepts == []
        assert rushed is False

    def test_unknown_concepts_filtered_out(self):
        reply = """OK.

```json
{"missed_concepts": ["idempotency_dedup", "fake_concept_xyz", "backfill_reprocessing"]}
```"""
        prose, concepts, rushed, score, note, rubric = split_wrap_up_reply(reply)
        assert "idempotency_dedup" in concepts
        assert "backfill_reprocessing" in concepts
        assert "fake_concept_xyz" not in concepts

    def test_ai_taxonomy_filtering(self):
        reply = """OK.

```json
{"missed_concepts": ["retrieval_relevance_chunking", "idempotency_dedup"]}
```"""
        prose, concepts, rushed, score, note, rubric = split_wrap_up_reply(reply, CONCEPT_TAXONOMY_AI)
        assert "retrieval_relevance_chunking" in concepts
        assert "idempotency_dedup" not in concepts

    def test_communication_score_boundary(self):
        # Valid scores 1-5
        for s in range(1, 6):
            reply = f"""OK.

```json
{{"communication_score": {s}}}
```"""
            _, _, _, score, _, _ = split_wrap_up_reply(reply)
            assert score == s

        # Out of range — should be None
        reply = """OK.

```json
{"communication_score": 6}
```"""
        _, _, _, score, _, _ = split_wrap_up_reply(reply)
        assert score is None

        reply = """OK.

```json
{"communication_score": 0}
```"""
        _, _, _, score, _, _ = split_wrap_up_reply(reply)
        assert score is None

    def test_rushed_to_design_boolean_coercion(self):
        reply = """OK.

```json
{"rushed_to_design": false}
```"""
        _, _, rushed, _, _, _ = split_wrap_up_reply(reply)
        assert rushed is False

        reply = """OK.

```json
{"rushed_to_design": 1}
```"""
        _, _, rushed, _, _, _ = split_wrap_up_reply(reply)
        assert rushed is True

    def test_empty_rubric_scores(self):
        reply = """OK.

```json
{"rubric_scores": {}}
```"""
        _, _, _, _, _, rubric = split_wrap_up_reply(reply)
        assert rubric == {}

    def test_missing_rubric_scores_key(self):
        reply = """OK.

```json
{"missed_concepts": []}
```"""
        _, _, _, _, _, rubric = split_wrap_up_reply(reply)
        assert rubric == {}


# ── Integration: rubric scores → verdict edge cases ──────────────────────

class TestRubricVerdictIntegration(unittest.TestCase):
    def test_all_phases_zero(self):
        scores = {f"phase{i+1}": 0 for i in range(6)}
        assert hire_verdict([], False, None, scores) == "No Hire"

    def test_all_phases_max(self):
        scores = {"phase1": 8, "phase2": 10, "phase3": 6, "phase4": 8, "phase5": 6, "phase6": 6}
        assert hire_verdict([], False, None, scores) == "Strong Hire"

    def test_missed_concepts_ignored_when_rubric_present(self):
        # With rubric_scores provided, missed_concepts don't affect verdict
        scores = {"phase1": 8, "phase2": 10, "phase3": 6, "phase4": 8, "phase5": 6, "phase6": 6}
        result = hire_verdict(["idempotency_dedup", "backfill_reprocessing"], False, None, scores)
        assert result == "Strong Hire"

    def test_rubric_with_invalid_phase_keys(self):
        # Extra or wrong keys — only phase1-phase6 are read
        scores = {"phase1": 8, "phase7": 10, "bogus": 5}
        # phase2-phase6 default to 0 → 8/44 = 18% → No Hire
        assert hire_verdict([], False, None, scores) == "No Hire"
