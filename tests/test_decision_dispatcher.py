"""Regression tests for JSON-driven classification routing."""
import os
import sys
import ctypes
import json
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# The application has Windows APIs, but these tests only exercise path resolution.
if not hasattr(ctypes, "windll"):
    class MockWinDLL:
        def __getattr__(self, name):
            class MockDLL:
                def __getattr__(self, func):
                    return lambda *args, **kwargs: 1
            return MockDLL()
    ctypes.windll = MockWinDLL()
    ctypes.WinDLL = lambda name, **kwargs: MockWinDLL()
if not hasattr(ctypes, "WINFUNCTYPE"):
    ctypes.WINFUNCTYPE = ctypes.CFUNCTYPE

for module_name in ("win32file", "win32con"):
    try:
        __import__(module_name)
    except ImportError:
        sys.modules[module_name] = type("Mock" + module_name, (), {})()
try:
    import pywintypes
except ImportError:
    sys.modules["pywintypes"] = type("MockPyWinTypes", (), {"error": Exception})
try:
    import send2trash
except ImportError:
    sys.modules["send2trash"] = type(
        "MockSend2Trash", (), {"send2trash": staticmethod(lambda path: True)}
    )

import config
from classification_registry import ClassificationRegistry
from decision_dispatcher import DecisionDispatcher
from fallback_utils import compute_destination

class TestDecisionDispatcher(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.internal=self.root/"Internal"
        self.internal.mkdir()
        self.conflicts=self.root/"Conflicts"
        self.docs=self.root/"Documents"
        self.family=self.root/"Family"
        self.config_path=self.root/"classifications.json"
        self.original={k:getattr(config,k) for k in ("CLASSIFICATIONS_JSON_PATH","BASE_INTERNAL","CONFLICTS","ONEDRIVE_DOCS","ONEDRIVE_DOCTOS_FAMILIA")}
        config.CLASSIFICATIONS_JSON_PATH=self.config_path
        config.BASE_INTERNAL=self.internal
        config.CONFLICTS=self.conflicts
        config.ONEDRIVE_DOCS=self.docs
        config.ONEDRIVE_DOCTOS_FAMILIA=self.family

    def tearDown(self):
        for key,value in self.original.items():
            setattr(config,key,value)
        self.temp.cleanup()

    def _write_decisions(self,decisions):
        self.config_path.write_text(json.dumps({"schema_version":2,"decisions":decisions}),encoding="utf-8")
        return ClassificationRegistry(self.config_path)

    def test_legacy_config_migrates_handlers_and_preserves_custom_decisions(self):
        legacy_decisions = [
            {
                "id": 2,
                "name": "Personajes",
                "name_key": "type_2",
                "icon": "me-gusta.png",
                "enabled": True,
                "order": 2,
                "handler": "subfolder_year",
                "year_mode": "required",
                "base_path": "{BASE_INTERNAL}/{year}/{year_prefix}. album",
                "folder_source": "filesystem",
            },
            {
                "id": 3,
                "name": "Episodios",
                "name_key": "type_3",
                "icon": "película.png",
                "enabled": True,
                "order": 3,
                "handler": "episode",
                "year_mode": "required",
                "folder_source": "filesystem",
            },
            {
                "id": 99,
                "name": "Custom",
                "handler": "move_to_subfolder",
                "year_mode": "none",
                "base_path": "D:/Custom",
                "folder_source": "filesystem",
            },
        ]
        self.config_path.write_text(
            json.dumps({"schema_version": 1, "decisions": legacy_decisions}),
            encoding="utf-8",
        )

        registry = ClassificationRegistry(self.config_path)

        characters = registry.get_decision(2)
        episodes = registry.get_decision(3)
        custom = registry.get_decision(99)
        self.assertEqual(characters["handler"], "move_to_subfolder")
        self.assertEqual(characters["folder_contains"], "album")
        self.assertEqual(
            characters["base_path"], "{BASE_INTERNAL}/{year}"
        )
        self.assertEqual(episodes["handler"], "move_to_subfolder")
        self.assertEqual(episodes["folder_contains"], "___[")
        self.assertEqual(episodes["behaviour_secon_line"], "last_file")
        self.assertIsNotNone(custom)
        self.assertEqual(custom["base_path"], "D:/Custom")

        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["schema_version"], 2)

    def test_episode_default_declares_folder_contains_and_secondary_line(self):
        episode=ClassificationRegistry(self.config_path).get_decision(3)
        self.assertEqual(episode["folder_contains"],"___[")
        self.assertEqual(episode["behaviour_secon_line"],"last_file")
        self.assertEqual(episode["handler"],"move_to_subfolder")

    def test_folder_contains_resolves_episode_parent_without_fixed_id(self):
        year_dir=self.internal/"2025"
        year_dir.mkdir()
        (year_dir/"22. Other folder").mkdir()
        expected=year_dir/"22. ___[Series]"
        expected.mkdir()
        decision={"id":99,"handler":"move_to_subfolder","year_mode":"required","base_path":"{BASE_INTERNAL}/{year}","folder_contains":"___[","folder_fallback":"{BASE_INTERNAL}/{year}"}
        registry=self._write_decisions([decision])
        self.assertEqual(DecisionDispatcher(registry=registry).resolve_base_path(decision,2025),expected)

    def test_compute_destination_uses_custom_id_and_folder_contains(self):
        year_dir=self.internal/"2025"
        year_dir.mkdir()
        episode_parent=year_dir/"22. ___[Series]"
        episode_parent.mkdir()
        source=self.root/"episode.mkv"
        source.write_bytes(b"video")
        definition={"id":99,"name":"Custom episodes","handler":"move_to_subfolder","year_mode":"required","base_path":"{BASE_INTERNAL}/{year}","folder_contains":"___[","folder_fallback":"{BASE_INTERNAL}/{year}","folder_source":"filesystem","enabled":True,"order":1}
        self._write_decisions([definition])
        destination=compute_destination({"movement_type":99,"year":2025,"sub":"Season 01","new_name":"episode-renamed"},source)
        expected=episode_parent/"Season 01"/"episode-renamed.mkv"
        self.assertEqual(destination,expected)
        self.assertTrue(expected.parent.is_dir())

    def test_folder_contains_is_case_insensitive_and_has_fallback(self):
        year_dir=self.internal/"2024"
        year_dir.mkdir()
        matched=year_dir/"18. ___[ARCHIVE]"
        matched.mkdir()
        decision={"id":91,"handler":"move_to_subfolder","year_mode":"required","base_path":"{BASE_INTERNAL}/{year}","folder_contains":"archive","folder_fallback":"{BASE_INTERNAL}/{year}/fallback"}
        dispatcher=DecisionDispatcher(registry=ClassificationRegistry(self.config_path))
        self.assertEqual(dispatcher.resolve_base_path(decision,2024),matched)
        matched.rmdir()
        self.assertEqual(dispatcher.resolve_base_path(decision,2024),year_dir/"fallback")

    def test_documents_use_the_configured_path_without_id_rules(self):
        decision={"id":42,"handler":"move_to_subfolder","year_mode":"none","base_path":"{ONEDRIVE_DOCS}","folder_source":"filesystem"}
        source=self.root/"notes.txt"
        source.write_text("notes",encoding="utf-8")
        destination=DecisionDispatcher(registry=ClassificationRegistry(self.config_path)).resolve_destination(decision,source,new_name="notes")
        self.assertEqual(destination,self.docs/"notes.txt")
        self.assertTrue(self.docs.is_dir())

if __name__=="__main__":
    unittest.main()
