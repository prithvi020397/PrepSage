"""Phase 2 characterization tests — pin current behavior of pure helpers that
will be moved into core/ and services/ in later refactor phases. These must
stay GREEN before AND after every move. No behavior changes allowed.

Covers: topic_for (both schemas), _repair_truncated_json, hire_verdict
banding thresholds, is_solved/is_due, schedule_review interval logic.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import app as a


class TestTopicFor(unittest.TestCase):
    def test_classic_schema_uses_prompt(self):
        q = {"lang": "sql", "title": "Second highest salary",
             "prompt": "find the second highest salary using a window function",
             "concept": "rank"}
        self.assertEqual(a.topic_for(q), "window functions")

    def test_v2_decomposition_schema_no_prompt(self):
        q = {"lang": "decomposition", "id": "decomp_hospital",
             "title": "Hospital readmission",
             "persona": "VP of clinical ops worried about readmissions",
             "triggers": ["regulatory reporting", "stakeholder alignment"],
             "rubric": "must discuss join strategy across tables"}
        self.assertIn(a.topic_for(q), [t for _, t in a.TOPIC_KEYWORDS] + ["other-decomposition"])

    def test_unknown_topic_falls_back_to_lang(self):
        q = {"lang": "python", "title": "mystery", "prompt": "zzz no keywords here"}
        self.assertEqual(a.topic_for(q), "other-python")


class TestRepairTruncatedJson(unittest.TestCase):
    def test_truncated_object_rebalanced(self):
        raw = '{"a": 1, "b": {"c": 2'
        repaired = a._repair_truncated_json(raw)
        self.assertEqual(a.json.loads(repaired), {"a": 1, "b": {"c": 2}})

    def test_truncated_array_rebalanced(self):
        raw = '{"items": [1, 2, 3'
        repaired = a._repair_truncated_json(raw)
        self.assertEqual(a.json.loads(repaired), {"items": [1, 2, 3]})

    def test_unterminated_string_closed(self):
        raw = '{"name": "partial'
        repaired = a._repair_truncated_json(raw)
        self.assertEqual(a.json.loads(repaired), {"name": "partial"})

    def test_trailing_comma_stripped(self):
        raw = '{"a": 1, "b": 2,}'
        repaired = a._repair_truncated_json(raw)
        self.assertEqual(a.json.loads(repaired), {"a": 1, "b": 2})

    def test_nested_truncation_lifo_closers(self):
        raw = '{"x": {"y": [1, 2'
        repaired = a._repair_truncated_json(raw)
        self.assertEqual(a.json.loads(repaired), {"x": {"y": [1, 2]}})


class TestHireVerdictBands(unittest.TestCase):
    def test_rubric_pct_strong_hire_boundary(self):
        scores = {"phase1": 8, "phase2": 10, "phase3": 6, "phase4": 8, "phase5": 6, "phase6": 6}
        self.assertEqual(a.hire_verdict([], False, None, rubric_scores=scores), "Strong Hire")

    def test_rubric_pct_hire_boundary(self):
        scores = {"phase1": 5, "phase2": 6, "phase3": 4, "phase4": 5, "phase5": 4, "phase6": 4}
        self.assertEqual(a.hire_verdict([], False, None, rubric_scores=scores), "Hire")

    def test_rubric_pct_no_hire_below(self):
        scores = {"phase1": 1, "phase2": 1, "phase3": 1, "phase4": 1, "phase5": 1, "phase6": 1}
        self.assertEqual(a.hire_verdict([], False, None, rubric_scores=scores), "No Hire")

    def test_points_strong_hire_zero(self):
        self.assertEqual(a.hire_verdict([], False, 3), "Strong Hire")

    def test_points_hire_boundary(self):
        # 1 missed (-1), not rushed, comm 3 -> -1 -> Hire (>= -3, < 0)
        self.assertEqual(a.hire_verdict(["a"], False, 3), "Hire")

    def test_points_no_hire_below(self):
        # 1 missed (-1), rushed (-2), comm 1 (-2) -> -5 -> No Hire (< -3)
        self.assertEqual(a.hire_verdict(["a"], True, 1), "No Hire")


class TestSolvedDue(unittest.TestCase):
    def setUp(self):
        self._snap = dict(a.PROGRESS)
        a.PROGRESS.clear()

    def tearDown(self):
        a.PROGRESS.clear()
        a.PROGRESS.update(self._snap)

    def test_is_solved_true_only_with_solved_at(self):
        a.PROGRESS["q1"] = {"solved_at": "2026-01-01T00:00:00"}
        a.PROGRESS["q2"] = {"trace_cache": "x"}
        self.assertTrue(a.is_solved("q1"))
        self.assertFalse(a.is_solved("q2"))
        self.assertFalse(a.is_solved("absent"))

    def test_is_due_respects_due_at(self):
        from datetime import datetime, timedelta
        past = (datetime.now() - timedelta(days=1)).isoformat()
        future = (datetime.now() + timedelta(days=1)).isoformat()
        a.PROGRESS["due_past"] = {"due_at": past}
        a.PROGRESS["due_future"] = {"due_at": future}
        self.assertTrue(a.is_due("due_past"))
        self.assertFalse(a.is_due("due_future"))
        self.assertFalse(a.is_due("absent"))


class TestScheduleReview(unittest.TestCase):
    def setUp(self):
        self._snap = dict(a.PROGRESS)
        a.PROGRESS.clear()
        a.PROGRESS.pop("_deadline", None)

    def tearDown(self):
        a.PROGRESS.clear()
        a.PROGRESS.pop("_deadline", None)
        a.PROGRESS.update(self._snap)

    def _interval_for(self, qid):
        from datetime import datetime
        e = a.PROGRESS[qid]
        return round((datetime.fromisoformat(e["due_at"]) - datetime.fromisoformat(e["solved_at"])).total_seconds() / 86400)

    def test_interval_zero_fails_is_seven_days(self):
        a.schedule_review("q1", 0)
        self.assertEqual(self._interval_for("q1"), 7)

    def test_interval_few_fails_is_three_days(self):
        a.schedule_review("q1", 2)
        self.assertEqual(self._interval_for("q1"), 3)

    def test_interval_many_fails_is_one_day(self):
        a.schedule_review("q1", 5)
        self.assertEqual(self._interval_for("q1"), 1)


if __name__ == "__main__":
    unittest.main()
