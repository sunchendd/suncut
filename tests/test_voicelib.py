import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sd import voicelib


class VoiceLibraryTest(unittest.TestCase):
    def test_builtin_edge_assets_use_distinct_engine_voices(self):
        assets = voicelib.edge_voices().values()
        engine_voices = [v["engine_voice"] for v in assets]
        self.assertEqual(len(engine_voices), len(set(engine_voices)))

    def test_only_approved_assets_are_selectable(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "catalog.json"
            path.write_text(json.dumps({"voices": [
                {"id": "safe", "engine": "edge_tts", "rights": {"approved": True}},
                {"id": "blocked", "engine": "edge_tts", "rights": {"approved": False}},
            ]}))
            with patch.object(voicelib, "CATALOG", path):
                self.assertEqual([v["id"] for v in voicelib.voices()], ["safe"])
                self.assertIsNone(voicelib.by_id("blocked"))

    def test_cosyvoice_requires_consent_reference(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "catalog.json"
            path.write_text(json.dumps({"voices": [{
                "id": "clone", "engine": "cosyvoice", "rights": {"approved": True}
            }]}))
            with patch.object(voicelib, "CATALOG", path):
                with self.assertRaises(ValueError):
                    voicelib.validate_selection("clone")
                self.assertEqual(voicelib.validate_selection("clone", "signed-consent")["id"], "clone")
