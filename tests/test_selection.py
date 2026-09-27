import json
import tempfile
import unittest
from pathlib import Path

from sd import av, quality
from sd.screenwriter import _durations


def full_review(video, verdict="pass"):
    return {"case": "p-q1", "video": str(video), "verdict": verdict,
            "text_artifacts": False, "identity": 8, "action": 8,
            "composition": 8, "story_facts": 9,
            "motion_naturalness": 8, "performance": 8}


class FakeProject:
    name = "p"

    def __init__(self, root, review, state):
        self.path = Path(root)
        self.video = self.path / "q1.mp4"
        self.video.write_bytes(b"video")
        self._review = review
        self._state = state

    def load_stage(self, stage):
        if stage == "script":
            return {"shots": [{"id": "q1"}]}
        if stage == "generate":
            return {"videos": {"p-q1": str(self.video)}}
        if stage == "review":
            return self._review
        raise AssertionError(stage)

    def load_state(self):
        return self._state


class SelectionTests(unittest.TestCase):
    def test_pick_best_blocks_legacy_scores_without_full_review(self):
        with tempfile.TemporaryDirectory() as td:
            p = FakeProject(td, {"results": [], "consistency": {"checked": True, "consistent": True}},
                            {"gen_scores": {"p-q1": {"identity": 10, "action": 10,
                                                       "composition": 10}}})
            with self.assertRaises(quality.QualityGateError):
                av.pick_best(p)

    def test_pick_best_accepts_full_bound_review(self):
        with tempfile.TemporaryDirectory() as td:
            p = FakeProject(td, {"results": [], "consistency": {"checked": True, "consistent": True}}, {})
            review = full_review(p.video)
            p._review = {"results": [review], "consistency": {"checked": True, "consistent": True}}
            p._state = {"gen_reviews": {"p-q1": review}}
            segs, picks = av.pick_best(p)
            self.assertEqual(segs, [str(p.video)])
            self.assertEqual(picks[0]["disposition"], "pass")

    def test_continuous_edit_duration_wins_over_legacy_hint(self):
        self.assertEqual(_durations([{"duration_hint": "std", "edit_duration_s": 3.35}]), [3.35])


if __name__ == "__main__":
    unittest.main()

