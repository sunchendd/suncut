import unittest

from sd import motionqc


class MotionQcTests(unittest.TestCase):
    def test_unmotivated_near_static_shot_is_hard_failure(self):
        metrics = {"mean_diff": 1.1, "motion_cv": .3, "center_edge": 1.0,
                   "near_static_pct": 72.0}
        self.assertTrue(motionqc.hard_failure(metrics, "he looks around the kitchen"))

    def test_static_prop_reveal_is_sent_to_vision_instead(self):
        metrics = {"mean_diff": 1.1, "motion_cv": .3, "center_edge": 1.0,
                   "near_static_pct": 72.0}
        intent = "Static locked-off close shot: a brass key rests beside a blank envelope."
        self.assertTrue(motionqc.allows_low_motion(intent))
        self.assertFalse(motionqc.hard_failure(metrics, intent))

    def test_uniform_motion_and_fake_locomotion_are_flagged(self):
        metrics = {"mean_diff": 4.0, "motion_cv": .04, "center_edge": 1.0,
                   "near_static_pct": 0.0}
        flags = motionqc.flags(metrics, "a man walks through a meadow")
        self.assertTrue(any("匀速" in flag for flag in flags))
        self.assertTrue(any("位移" in flag for flag in flags))


if __name__ == "__main__":
    unittest.main()
