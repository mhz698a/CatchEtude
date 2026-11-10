import unittest
from pathlib import Path
import tempfile
import shutil
from types import SimpleNamespace
from unittest.mock import Mock, patch

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

    def test_properties_dialog_without_character_starts_traditional_scan(self):
        worker = Mock()
        with patch(
            "folder_properties_dialog.FolderStatsWorker", return_value=worker
        ), patch.object(FolderPropertiesDialog, "_attach_scan_worker") as attach:
            dialog = FolderPropertiesDialog(self.test_folder)
            attach.assert_called_once_with(dialog, worker)
            worker.progress.connect.assert_called_once()
            worker.stats_ready.connect.assert_called_once()
            worker.scan_failed.connect.assert_called_once()
            self.assertFalse(hasattr(dialog, "traditional_scan_button"))
            dialog.close()

    def test_scan_folder_stats_and_format(self):
        file_count, total_bytes = scan_folder_stats(self.test_folder)
        self.assertEqual(file_count, 2)
        self.assertGreater(total_bytes, 0)

        formatted = format_bytes(total_bytes)
        self.assertIn("KB", formatted)
        self.assertIn("bytes", formatted)

    def test_opening_properties_uses_valid_cache_without_starting_worker(self):
        cached = {"file_count": 8, "total_size": 4096, "entry_count": 3}
        with patch.object(
            FolderPropertiesDialog, "_read_valid_folder_cache", return_value=cached
        ), patch("folder_properties_dialog.FolderStatsWorker") as worker_class:
            dialog = FolderPropertiesDialog(self.test_folder)
            worker_class.assert_not_called()
            self.assertEqual(dialog.files_value.text(), "8")
            self.assertIn("4.0 KB", dialog.size_value.text())
            self.assertEqual(
                dialog.status_label.text(), dialog.loc.get("lbl_prop_cache_used")
            )
            self.assertIsNone(dialog._scan_worker)
            dialog.close()

    def test_traditional_scan_uses_valid_character_cache(self):
        cache = Mock()
        cache.get_folder_data.return_value = {
            "mtime_ns": self.test_folder.stat().st_mtime_ns,
            "entry_count": 4,
            "file_count": 12,
            "total_size": 4096,
        }
        character = SimpleNamespace(
            year=2024, num=1, alter="A", name="Test",
            birthday_iso="1970-01-01", origin_age=0, age_str="",
        )
        with patch("character_cache_mgr.CharacterCacheManager", return_value=cache), patch(
            "folder_properties_dialog.FolderStatsWorker"
        ) as worker_class:
            dialog = FolderPropertiesDialog(self.test_folder, char_entry=character)

            cache.get_folder_data.assert_called_once_with(str(self.test_folder))
            worker_class.assert_not_called()
            self.assertEqual(dialog.files_value.text(), "12")
            self.assertIn("4.0 KB", dialog.size_value.text())
            self.assertEqual(dialog.status_label.text(), dialog.loc.get("lbl_prop_cache_used"))
            self.assertIsNone(dialog._scan_worker)
            dialog.close()

    def test_traditional_scan_uses_valid_overworld_cache(self):
        cache = Mock()
        cache.get_folder_data.return_value = {
            "mtime_ns": self.test_folder.stat().st_mtime_ns,
            "file_count": 7,
            "total_size": 2048,
            "size_mb_str": "0.0 MB",
        }
        with patch("overworld_cache_mgr.OverworldCacheManager", return_value=cache), patch(
            "folder_properties_dialog.FolderStatsWorker"
        ) as worker_class:
            dialog = FolderPropertiesDialog(self.test_folder, overworld_year=2025)

            cache.get_folder_data.assert_called_once_with(str(self.test_folder))
            worker_class.assert_not_called()
            self.assertEqual(dialog.files_value.text(), "7")
            self.assertIn("2.0 KB", dialog.size_value.text())
            self.assertIsNone(dialog._scan_worker)
            dialog.close()

    def test_stale_character_cache_falls_back_to_traditional_worker(self):
        cache = Mock()
        cache.get_folder_data.return_value = {
            "mtime_ns": self.test_folder.stat().st_mtime_ns - 1,
            "entry_count": 4,
            "file_count": 12,
            "total_size": 4096,
        }
        worker = Mock()
        character = SimpleNamespace(year=2024)
        with patch("character_cache_mgr.CharacterCacheManager", return_value=cache), patch(
            "folder_properties_dialog.FolderStatsWorker", return_value=worker
        ), patch.object(FolderPropertiesDialog, "_attach_scan_worker") as attach:
            dialog = FolderPropertiesDialog(self.test_folder, char_entry=character)
            attach.assert_called_once_with(dialog, worker)
            self.assertIsNone(dialog._scan_worker)
            dialog.close()

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
        with patch.object(FolderPropertiesDialog, "_start_traditional_scan"):
            dialog = FolderPropertiesDialog(self.test_folder, char_entry=entry)
        self.assertIn("TestCharacterFolder", dialog.windowTitle())
        dialog.close()

    def test_traditional_scan_success_refreshes_existing_character_cache(self):
        cache = Mock()
        character = SimpleNamespace(
            year=2024, num=2, alter="B", name="Test",
            birthday_iso="2000-01-01", origin_age=10, age_str="",
        )
        with patch("character_cache_mgr.CharacterCacheManager", return_value=cache), patch.object(
            FolderPropertiesDialog, "_start_traditional_scan"
        ):
            dialog = FolderPropertiesDialog(self.test_folder, char_entry=character)
            folder_mtime_ns = self.test_folder.stat().st_mtime_ns
            dialog._on_scan_ready(5, 8192, 3, folder_mtime_ns)
            cache.update_folder.assert_called_once()
            args = cache.update_folder.call_args.args
            self.assertEqual(args[0], str(self.test_folder))
            self.assertEqual(args[2:5], (3, 5, 8192))
            cache.save.assert_called_once()
            dialog.close()

    def test_traditional_scan_success_refreshes_existing_overworld_cache(self):
        cache = Mock()
        with patch("overworld_cache_mgr.OverworldCacheManager", return_value=cache), patch.object(
            FolderPropertiesDialog, "_start_traditional_scan"
        ):
            dialog = FolderPropertiesDialog(self.test_folder, overworld_year=2025)
            folder_mtime_ns = self.test_folder.stat().st_mtime_ns
            dialog._on_scan_ready(9, 16384, 2, folder_mtime_ns)
            cache.update_folder.assert_called_once()
            args = cache.update_folder.call_args.args
            self.assertEqual(args[0], str(self.test_folder))
            self.assertEqual(args[2:4], (9, 16384))
            cache.save.assert_called_once()
            dialog.close()

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
