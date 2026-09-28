import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sd import av, config
from sd.project import Project


class LandscapeOnlyTests(unittest.TestCase):
    def test_only_landscape_is_public_orientation(self):
        self.assertEqual(config.ORIENTATIONS, ("landscape",))

    def test_old_portrait_project_reads_as_landscape_and_migrates_on_save(self):
        with tempfile.TemporaryDirectory() as root, patch.object(config, "PROJECTS", Path(root)):
            p = Project("old")
            p.create("brief", 1, orientation="portrait")
            self.assertEqual(p.settings()["orientation"], "landscape")
            with self.assertRaises(ValueError):
                p.update_settings(orientation="portrait")
            p.update_settings(resolution="720p")
            self.assertEqual(p.load_state()["orientation"], "landscape")

    def test_export_filter_rejects_portrait(self):
        with self.assertRaises(ValueError):
            av.orient_vf(1080, 1920, "portrait")


if __name__ == "__main__":
    unittest.main()
