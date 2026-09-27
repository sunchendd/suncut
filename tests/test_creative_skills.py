import unittest

from sd import creative_skills


class CreativeSkillsTests(unittest.TestCase):
    def test_all_eight_agents_have_loadable_skills(self):
        expected = {"casting", "materials", "screenwriter", "storyboard",
                    "director", "reviewer", "dubbing", "producer"}
        self.assertEqual(set(creative_skills.inventory()), expected)
        for agent in expected:
            text = creative_skills.prompt_for(agent)
            self.assertIn("项目级 Skill", text)
            self.assertGreater(len(text), 30)


if __name__ == "__main__":
    unittest.main()

