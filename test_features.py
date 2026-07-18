"""Tests for the whiteboard scoring signal and calibration mode (features shipped for D2/D4
diagram scoring and the "Calibrate vs gold" comparison)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from app import app, CALIBRATION_FIXTURES, build_judge_transcript, WHITEBOARD_WRAP_RE


class TestCalibrationFixtures(unittest.TestCase):
    def test_hospital_scenario_has_three_golds(self):
        golds = CALIBRATION_FIXTURES.get("decomp_hospital_readmission", [])
        self.assertEqual(len(golds), 3)

    def test_agri_scenario_has_karthik_gold(self):
        golds = CALIBRATION_FIXTURES.get("decomposition-7", [])
        self.assertEqual(len(golds), 1)
        self.assertIn("dimension_assertions", golds[0]["expected"])

    def test_each_gold_exposes_dimension_assertions(self):
        for sid, golds in CALIBRATION_FIXTURES.items():
            for g in golds:
                asserts = g["expected"].get("dimension_assertions", {})
                self.assertIn("D2", asserts,
                               f"fixture {g['file']} missing D2 assertion")


class TestCalibrationEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_decomposition_1_maps_to_hospital_golds(self):
        # decomposition-1 is an alias for decomp_hospital_readmission
        resp = self.client.post("/api/calibration",
                                 json={"question_id": "decomposition-1"})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(len(data["golds"]), 3)
        self.assertIn("D1", data["dimensions"])
        self.assertIn("D8", data["dimensions"])

    def test_unknown_scenario_returns_404(self):
        resp = self.client.post("/api/calibration",
                                 json={"question_id": "no_such_scenario"})
        self.assertEqual(resp.status_code, 404)

    def test_missing_question_id_returns_400(self):
        resp = self.client.post("/api/calibration", json={})
        self.assertEqual(resp.status_code, 400)

    def test_gold_carries_expected_band_and_ranges(self):
        resp = self.client.post("/api/calibration",
                                 json={"question_id": "decomposition-1"})
        data = resp.get_json()
        strong = next(g for g in data["golds"] if g["band"] == "strong_hire")
        self.assertIn("D4", strong["dimension_assertions"])
        self.assertIn("min", strong["dimension_assertions"]["D4"])


class TestWhiteboardSignal(unittest.TestCase):
    def test_whiteboard_extracted_into_judge_transcript(self):
        turns = [
            {"role": "user", "content": "[Candidate's current whiteboard]\n"
                                       "Box: Kafka [source]\nArrow: Kafka -> Spark [processing]\n\n"
                                       "[Candidate says]\nI'll stream events through Kafka.",
             "turn": 0},
            {"role": "assistant", "content": "Good. Tell me about the sink.", "turn": 1},
        ]
        out = build_judge_transcript(turns)
        self.assertEqual(out[0]["role"], "candidate")
        self.assertIn("Kafka", out[0]["whiteboard"])
        self.assertIn("Spark", out[0]["whiteboard"])
        # client turns have no whiteboard field
        self.assertNotIn("whiteboard", out[1])

    def test_turn_without_whiteboard_has_no_whiteboard_field(self):
        turns = [{"role": "user", "content": "Just talking, no diagram yet.", "turn": 0}]
        out = build_judge_transcript(turns)
        self.assertNotIn("whiteboard", out[0])

    def test_whiteboard_text_truncation_separate_from_diagram(self):
        long_speech = "x" * 5000
        diagram = "Box: A [source]"
        turns = [{"role": "user",
                  "content": f"[Candidate's current whiteboard]\n{diagram}\n\n[Candidate says]\n{long_speech}",
                  "turn": 0}]
        out = build_judge_transcript(turns)
        # diagram preserved in full, speech truncated to 2000 in the text field
        self.assertIn("Box: A", out[0]["whiteboard"])
        self.assertLessEqual(len(out[0]["text"]), 2000)


if __name__ == "__main__":
    unittest.main()
