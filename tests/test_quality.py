import json
import tempfile
import unittest
from pathlib import Path

from sd import quality


def good_review():
    return {"verdict": "pass", "text_artifacts": False,
            "identity": 8, "action": 8, "composition": 8,
            "story_facts": 9, "motion_naturalness": 8, "performance": 8}


class QualityTests(unittest.TestCase):
    def test_legacy_three_scores_never_count_as_complete_pass(self):
        self.assertFalse(quality.review_is_pass(
            {"verdict": "pass", "identity": 9, "action": 9, "composition": 9}))

    def test_text_artifact_is_hard_failure(self):
        review = good_review()
        review["text_artifacts"] = True
        self.assertFalse(quality.review_is_pass(review))

    def test_human_waiver_is_bound_to_video_and_reason(self):
        h = {"approved": True, "note": "导演确认可接受", "video": "/a.mp4"}
        self.assertTrue(quality.human_waiver_is_valid(h, "/a.mp4"))
        self.assertFalse(quality.human_waiver_is_valid(h, "/b.mp4"))
        h["note"] = ""
        self.assertFalse(quality.human_waiver_is_valid(h, "/a.mp4"))

    def test_release_gate_blocks_any_hold(self):
        picks = [{"case": "p-q1", "picked": "/q1.mp4", "disposition": "pass",
                  "review": good_review()},
                 {"case": "p-q2", "picked": "/q2.mp4", "disposition": "hold",
                  "review": {"verdict": "retake", "advice_cn": "重拍"}}]
        with self.assertRaises(quality.QualityGateError) as ctx:
            quality.assert_release_ready(picks, {"checked": True, "consistent": True})
        self.assertEqual(ctx.exception.report["holds"][0]["case"], "p-q2")

    def test_release_gate_blocks_cross_shot_inconsistency(self):
        picks = [{"case": "p-q1", "picked": "/q1.mp4", "disposition": "pass",
                  "review": good_review()}]
        with self.assertRaises(quality.QualityGateError):
            quality.assert_release_ready(picks, {"checked": True, "consistent": False})


if __name__ == "__main__":
    unittest.main()

