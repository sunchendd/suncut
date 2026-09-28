import unittest

from sd import director
from sd.storyboard import story_contract_hash


class RetakeContractTests(unittest.TestCase):
    def test_story_contract_changes_when_a_locked_fact_changes(self):
        shot = {"id": "q1", "cast": ["A"], "action_en": "A looks down",
                "locked_facts": ["A sees one blank envelope"]}
        before = story_contract_hash(shot)
        shot["locked_facts"] = ["A sees one brass key"]
        self.assertNotEqual(before, story_contract_hash(shot))

    def test_retake_plan_prioritizes_artifact_and_fact_repair(self):
        row = {"locked_facts": ["one blank envelope lies on the table"]}
        review = {"text_artifacts": True, "story_facts": 4,
                  "identity": 5, "identity_threshold": 7,
                  "motion_naturalness": 6, "performance": 5}
        plan = director._retake_plan(row, "remove the jar", review)
        self.assertEqual(plan["immutable_facts"], row["locked_facts"])
        self.assertIn("no readable text, label, symbol, UI, or writing", plan["prohibitions"])
        self.assertGreaterEqual(len(plan["priorities"]), 4)


if __name__ == "__main__":
    unittest.main()
