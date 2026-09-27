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
