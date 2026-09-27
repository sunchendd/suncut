import unittest

from sd import lint


class GenerationFeasibilityTests(unittest.TestCase):
    def test_rejects_multi_actor_and_small_prop_animation(self):
        shots = [{"id": "q1", "cast": ["A", "B"],
                  "locked_facts": ["A holds key", "B receives key"],
                  "action_en": "A key slides and spins beside the envelope."}]
        issues = lint.lint_generation_feasibility(shots)
        self.assertEqual(len(issues), 3)

    def test_allows_single_actor_single_result(self):
        shots = [{"id": "q1", "cast": ["A"],
                  "locked_facts": ["A stands still at the window"],
                  "action_en": "A turns toward the window and holds still."}]
        self.assertEqual(lint.lint_generation_feasibility(shots), [])

    def test_rejects_text_screen_and_dense_action_chain(self):
        shots = [{"id": "q2", "cast": ["A"], "locked_facts": ["A stops"],
                  "action_en": "A drops a phone, grips a key, sweeps a bag up, turns and steps away."}]
        issues = lint.lint_generation_feasibility(shots)
        self.assertTrue(any("手机屏幕" in issue for issue in issues))
        self.assertTrue(any("可见动作" in issue for issue in issues))

    def test_phone_fallback_removes_screen_and_preserves_reaction(self):
        shot = {"id": "q4", "cast": ["A"], "action_en": "A drops a phone.",
                "locked_facts": ["phone is visible"]}
        self.assertIn("画外声音", lint.apply_generation_fallback(shot))
        self.assertEqual(lint.lint_generation_feasibility([shot]), [])
        self.assertIn("offscreen telephone", shot["action_en"])
