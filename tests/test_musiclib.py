import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sd import config, musiclib


class FakeProject:
    def __init__(self, root):
        self.path = Path(root)
        (self.path / "audio").mkdir(parents=True)


class MusicLibraryTests(unittest.TestCase):
    def test_sha_mismatch_is_not_ready(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            library = root / "library"
            library.mkdir()
            (library / "licensed.mp3").write_bytes(b"music" * 300)
            track = {"file": "licensed.mp3", "sha256": "0" * 64}
            with patch.object(config, "MUSIC_LIBRARY", library):
                self.assertFalse(musiclib.is_ready(track))

    def test_only_approved_catalog_track_can_be_selected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            library = root / "library"
            library.mkdir()
            (library / "licensed.mp3").write_bytes(b"music" * 300)
            catalog = library / "catalog.json"
            catalog.write_text(json.dumps({"tracks": [{"id": "warm", "file": "licensed.mp3",
                "rights": {"approved": True}, "mood_tags": ["warm"], "bpm": 82}]}))
            project = FakeProject(root / "project")
            with patch.object(config, "MUSIC_LIBRARY", library), patch.object(config, "MUSIC_CATALOG", catalog):
                selected = musiclib.write_selection(project, "warm")
                self.assertEqual(selected["track_id"], "warm")
                materialized = musiclib.materialize_selected_bgm(project)
                self.assertTrue(Path(materialized["materialized_file"]).is_file())

    def test_unapproved_track_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            library = root / "library"
            library.mkdir()
            catalog = library / "catalog.json"
            catalog.write_text(json.dumps({"tracks": [{"id": "unsafe", "file": "x.mp3",
                "rights": {"approved": False}}]}))
            project = FakeProject(root / "project")
            with patch.object(config, "MUSIC_LIBRARY", library), patch.object(config, "MUSIC_CATALOG", catalog):
                with self.assertRaises(musiclib.MusicLibraryError):
                    musiclib.write_selection(project, "unsafe")


if __name__ == "__main__":
    unittest.main()
