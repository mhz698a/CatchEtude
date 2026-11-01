import unittest
import sys
import ctypes
from pathlib import Path
import tempfile
import shutil

if not hasattr(ctypes, 'windll'):
    class MockWinDLL:
        def __getattr__(self, name):
            class MockDLL:
                def __getattr__(self, func):
                    return lambda *args, **kwargs: 1
            return MockDLL()
    ctypes.windll = MockWinDLL()
    ctypes.WinDLL = lambda name: MockWinDLL()

if not hasattr(ctypes, 'WINFUNCTYPE'):
    ctypes.WINFUNCTYPE = ctypes.CFUNCTYPE

from PyQt6 import QtWidgets, QtCore
from character_mgr import CharacterEntry, CharacterDelegate
from folder_properties_dialog import FolderPropertiesDialog, scan_folder_stats, format_bytes

class TestFolderProperties(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QtWidgets.QApplication.instance():
            cls.app = QtWidgets.QApplication([])
        else:
            cls.app = QtWidgets.QApplication.instance()

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.test_folder = Path(self.tmp_dir) / "TestCharacterFolder"
        self.test_folder.mkdir()
        (self.test_folder / "file1.txt").write_text("Hello World")
        (self.test_folder / "file2.txt").write_text("CatchEtude Properties Test")

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_scan_folder_stats_and_format(self):
        file_count, total_bytes = scan_folder_stats(self.test_folder)
        self.assertEqual(file_count, 2)
        self.assertGreater(total_bytes, 0)

        formatted = format_bytes(total_bytes)
        self.assertIn("KB", formatted)
        self.assertIn("bytes", formatted)

    def test_properties_dialog_without_character(self):
        dialog = FolderPropertiesDialog(self.test_folder)
        self.assertIn("TestCharacterFolder", dialog.windowTitle())

    def test_properties_dialog_with_character_entry(self):
        entry = CharacterEntry(
            year=2022,
            num=1,
            alter="A",
            name="TestChar",
            birthday_iso="2005-06-15",
            origin_age=14,
            file_count=2,
            total_size=100,
            path=str(self.test_folder),
            age_str="19.2 años",
            size_mb_str="0.1 MB"
        )
        dialog = FolderPropertiesDialog(self.test_folder, char_entry=entry)
        self.assertIn("TestCharacterFolder", dialog.windowTitle())

    def test_character_line3_no_files_string(self):
        entry = CharacterEntry(
            year=2022,
            num=1,
            alter="A",
            name="TestChar",
            birthday_iso="2005-06-15",
            origin_age=14,
            file_count=2,
            total_size=100,
            path=str(self.test_folder),
            age_str="19.2 años",
            size_mb_str="0.1 MB"
        )
        real_age = f"{entry.age_str} | " if entry.age_str else ""
        distance = "" if entry.origin_age == 0 else f"d: {(entry.year - 2003) - entry.origin_age} | "
        oring_age_fix = "" if entry.origin_age == 0 else f"a: {entry.origin_age} | "
        line3 = f"{real_age}{distance}{oring_age_fix}".strip().rstrip("|").strip()

        self.assertNotIn("Files:", line3)
        self.assertNotIn("MB", line3)
        self.assertEqual(line3, "19.2 años | d: 5 | a: 14")

if __name__ == "__main__":
    unittest.main()
