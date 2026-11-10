import unittest
import sys
import ctypes
from pathlib import Path
import tempfile
import shutil
import struct
from types import SimpleNamespace
from unittest.mock import Mock, patch

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
from ntfs_mft import (
    ElevationCancelledError,
    ElevationRequiredError,
    MFTScanner,
    MFTScanCancelled,
    UnsupportedFilesystemError,
    VolumeInfo,
    parse_usn_enum_buffer,
)
from ntfs_mft.errors import MFTAccessError, MFTEnumerationError, MFTRecordVersionError


def _usn_v2_record(file_reference, parent_reference, name, attributes=0, major=2, minor=0):
    encoded_name = name.encode("utf-16-le")
    name_offset = 60
    record_length = (name_offset + len(encoded_name) + 7) & ~7
    record = bytearray(record_length)
    struct.pack_into("<IHH", record, 0, record_length, major, minor)
    struct.pack_into("<QQ", record, 8, file_reference, parent_reference)
    struct.pack_into("<Q", record, 24, 0)
    struct.pack_into("<q", record, 32, 0)
    struct.pack_into("<IIII", record, 40, 0, 0, 0, attributes)
    struct.pack_into("<HH", record, 56, len(encoded_name), name_offset)
    record[name_offset:name_offset + len(encoded_name)] = encoded_name
    return bytes(record)


def _usn_page(next_reference, *records):
    return struct.pack("<Q", next_reference) + b"".join(records)


class FakeMFTApi:
    def __init__(self, filesystem="NTFS", elevated=True, inaccessible=()):
        self.volume = VolumeInfo(filesystem, "E:\\", "\\\\.\\E:")
        self.elevated = elevated
        self.inaccessible = set(inaccessible)
        self.opened = False
        self.closed = False
        self.closed_handles = []
        self.file_size_hints = []
        self.records = [
            _usn_v2_record(20, 10, "nested", 0x10),
            _usn_v2_record(30, 10, "one.bin", 0),
            _usn_v2_record(40, 20, "two.bin", 0),
            _usn_v2_record(50, 10, "desktop.ini", 0),
            _usn_v2_record(60, 10, "junction", 0x10 | 0x400),
            _usn_v2_record(70, 60, "outside.bin", 0),
        ]

    def get_volume_info(self, path):
        return self.volume

    def is_process_elevated(self):
        return self.elevated

    def get_file_reference(self, path):
        return 10

    def open_file_hint(self, path):
        return "directory-hint"

    def open_volume(self, volume):
        self.opened = True
        return "volume-handle"

    def close_handle(self, handle):
        self.closed_handles.append(handle)
        if handle == "volume-handle":
            self.closed = True

    def enumerate_usn_data(self, volume_handle, start_reference, buffer_size):
        if start_reference == 0:
            return _usn_page(1000, *self.records)
        return None

    def get_file_size_by_id(self, file_hint_handle, file_reference):
        self.file_size_hints.append(file_hint_handle)
        if file_reference in self.inaccessible:
            raise MFTAccessError("access denied")
        return {30: 10, 40: 20}[file_reference]


class TestNTFSMFTLibrary(unittest.TestCase):
    def test_parse_usn_record_v2(self):
        raw = _usn_page(123, _usn_v2_record(55, 44, "video.mp4", 0x20))
        next_reference, entries = parse_usn_enum_buffer(raw)
        self.assertEqual(next_reference, 123)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].file_reference, 55)
        self.assertEqual(entries[0].parent_reference, 44)
        self.assertEqual(entries[0].name, "video.mp4")
        self.assertFalse(entries[0].is_directory)

    def test_parser_rejects_unknown_record_versions(self):
        raw = _usn_page(10, _usn_v2_record(1, 0, "file", major=3))
        with self.assertRaises(MFTRecordVersionError):
            parse_usn_enum_buffer(raw)

    def test_parser_rejects_truncated_records(self):
        raw = struct.pack("<Q", 10) + struct.pack("<IHH", 80, 2, 0)
        with self.assertRaises(MFTEnumerationError):
            parse_usn_enum_buffer(raw)

    def test_mft_scan_counts_only_files_inside_selected_subtree(self):
        api = FakeMFTApi()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "target"
            folder.mkdir()
            result = MFTScanner(api=api).scan_folder(folder)

        self.assertEqual(result.file_count, 2)
        self.assertEqual(result.total_size, 30)
        self.assertEqual(result.root_entry_count, 4)
        self.assertEqual(result.inaccessible_count, 0)
        self.assertTrue(result.complete)
        self.assertTrue(api.opened)
        self.assertTrue(api.closed)
        self.assertCountEqual(
            api.closed_handles, ["directory-hint", "volume-handle"]
        )
        self.assertEqual(api.file_size_hints, ["directory-hint", "directory-hint"])

    def test_mft_scan_paginates_using_returned_next_file_reference_number(self):
        class PaginatedApi(FakeMFTApi):
            def __init__(self):
                super().__init__()
                self.requested_start_refs = []

            def enumerate_usn_data(self, volume_handle, start_reference, buffer_size):
                self.requested_start_refs.append(start_reference)
                if start_reference == 0:
                    return _usn_page(100, *self.records[:3])
                if start_reference == 100:
                    return _usn_page(1000, *self.records[3:])
                return None

        api = PaginatedApi()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "target"
            folder.mkdir()
            result = MFTScanner(api=api).scan_folder(folder)

        self.assertEqual(api.requested_start_refs, [0, 100, 1000])
        self.assertEqual(result.file_count, 2)
        self.assertEqual(result.total_size, 30)
        self.assertEqual(result.records_scanned, 6)

    def test_cancelled_mft_scan_closes_file_and_volume_handles(self):
        api = FakeMFTApi()
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "target"
            folder.mkdir()
            with self.assertRaises(MFTScanCancelled):
                MFTScanner(api=api, should_stop=lambda: True).scan_folder(folder)

        self.assertCountEqual(
            api.closed_handles, ["directory-hint", "volume-handle"]
        )

    def test_mft_scan_reports_unreadable_file_sizes_as_partial(self):
        api = FakeMFTApi(inaccessible={30})
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "target"
            folder.mkdir()
            result = MFTScanner(api=api).scan_folder(folder)

        self.assertEqual(result.file_count, 2)
        self.assertEqual(result.total_size, 20)
        self.assertEqual(result.inaccessible_count, 1)
        self.assertFalse(result.complete)

    def test_non_ntfs_volume_is_rejected_before_elevation_or_scan(self):
        api = FakeMFTApi(filesystem="exFAT", elevated=True)
        api.is_process_elevated = lambda: self.fail("Elevation must not be queried for a non-NTFS volume")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "target"
            folder.mkdir()
            with self.assertRaises(UnsupportedFilesystemError):
                MFTScanner(api=api).scan_folder(folder)
        self.assertFalse(api.opened)

    def test_mft_scan_requires_an_elevated_process(self):
        api = FakeMFTApi(elevated=False)
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "target"
            folder.mkdir()
            with self.assertRaises(ElevationRequiredError):
                MFTScanner(api=api).scan_folder(folder)
        self.assertFalse(api.opened)

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
        self.assertIsNone(dialog._scan_worker)
        self.assertEqual(dialog.files_value.text(), "—")
        self.assertEqual(dialog.size_value.text(), "—")
        self.assertEqual(dialog.traditional_scan_button.text(), dialog.loc.get("btn_prop_scan_traditional"))
        self.assertEqual(dialog.mft_scan_button.text(), dialog.loc.get("btn_prop_scan_mft"))
        self.assertFalse(dialog.progress_bar.isVisible())
        dialog.close()

    def test_mft_scan_initial_progress_text_has_no_unformatted_placeholder(self):
        dialog = FolderPropertiesDialog(self.test_folder)
        try:
            self.assertTrue(dialog._prepare_scan("mft"))
            self.assertNotIn("{records}", dialog.status_label.text())
            self.assertIn("0", dialog.status_label.text())
        finally:
            dialog.close()

    def test_opening_properties_does_not_start_a_scan(self):
        dialog = FolderPropertiesDialog(self.test_folder)
        dialog.show()
        self.app.processEvents()
        self.assertIsNone(dialog._scan_worker)
        dialog.close()

    def test_mft_button_rejects_non_ntfs_without_launching_uac_helper(self):
        with patch(
            "folder_properties_dialog.get_volume_info",
            return_value=VolumeInfo("exFAT", "E:\\\\", "\\\\.\\E:"),
        ), patch("folder_properties_dialog.MFTFolderStatsWorker") as worker_class, patch.object(
            QtWidgets.QMessageBox, "information", return_value=QtWidgets.QMessageBox.StandardButton.Ok
        ) as information:
            dialog = FolderPropertiesDialog(self.test_folder)
            dialog._start_mft_scan()
            information.assert_called_once()
            worker_class.assert_not_called()
            self.assertIsNone(dialog._scan_worker)
            dialog.close()

    def test_mft_button_starts_isolated_elevated_worker_without_elevating_main_app(self):
        worker = Mock()
        with patch(
            "folder_properties_dialog.get_volume_info",
            return_value=VolumeInfo("NTFS", "E:\\\\", "\\\\.\\E:"),
        ), patch(
            "folder_properties_dialog.MFTFolderStatsWorker", return_value=worker
        ) as worker_class:
            dialog = FolderPropertiesDialog(self.test_folder)
            dialog._attach_scan_worker = Mock()
            dialog._start_mft_scan()

            worker_class.assert_called_once_with(self.test_folder)
            dialog._attach_scan_worker.assert_called_once_with(worker)
            worker.progress.connect.assert_called_once()
            worker.stats_ready.connect.assert_called_once()
            worker.scan_failed.connect.assert_called_once()
            worker.scan_cancelled.connect.assert_called_once()
            self.assertEqual(dialog._scan_mode, "mft")
            dialog.close()

    def test_build_helper_launch_uses_pythonw_and_module_entrypoint_in_source_mode(self):
        from ntfs_mft.elevation import build_helper_launch

        with patch("ntfs_mft.elevation.sys.frozen", False, create=True):
            executable, arguments, working_directory = build_helper_launch()

        self.assertTrue(Path(executable).is_file())
        self.assertEqual(arguments, ["-m", "ntfs_mft.elevated_worker"])
        self.assertTrue(Path(working_directory).is_dir())

    def test_uac_cancel_is_reported_without_starting_scan(self):
        from ntfs_mft.elevation import _launch_with_uac

        shell32 = Mock()
        shell32.ShellExecuteExW.return_value = 0
        with patch("ntfs_mft.elevation.os.name", "nt"), patch(
            "ntfs_mft.elevation.ctypes.WinDLL", side_effect=[shell32, Mock()]
        ), patch("ntfs_mft.elevation.ctypes.get_last_error", return_value=1223, create=True):
            with self.assertRaises(ElevationCancelledError):
                _launch_with_uac(
                    "pythonw.exe", ["-m", "ntfs_mft.elevated_worker"], r"C:\\CatchEtude"
                )

    def test_elevated_launcher_requests_runas_and_keeps_process_handle(self):
        from ntfs_mft.elevation import _launch_with_uac

        shell32 = Mock()
        kernel32 = Mock()

        def fake_shell_execute(info_pointer):
            info_pointer._obj.hProcess = 1234
            return 1

        shell32.ShellExecuteExW.side_effect = fake_shell_execute
        with patch("ntfs_mft.elevation.os.name", "nt"), patch(
            "ntfs_mft.elevation.ctypes.WinDLL", side_effect=[shell32, kernel32]
        ):
            process_handle, returned_kernel32 = _launch_with_uac(
                "pythonw.exe", ["-m", "ntfs_mft.elevated_worker"], r"C:\\CatchEtude"
            )

        self.assertEqual(process_handle, 1234)
        self.assertIs(returned_kernel32, kernel32)
        shell_info = shell32.ShellExecuteExW.call_args.args[0]._obj
        self.assertEqual(shell_info.lpVerb, "runas")
        self.assertEqual(shell_info.lpFile, "pythonw.exe")
        self.assertEqual(shell_info.fMask, 0x40)

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
            dialog._start_traditional_scan()

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
            dialog._start_traditional_scan()

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
        ) as worker_class:
            dialog = FolderPropertiesDialog(self.test_folder, char_entry=character)
            dialog._attach_scan_worker = Mock()
            dialog._start_traditional_scan()

            worker_class.assert_called_once_with(self.test_folder)
            dialog._attach_scan_worker.assert_called_once_with(worker)
            self.assertEqual(dialog._scan_mode, "traditional")
            dialog.close()

    def test_mft_success_refreshes_existing_character_cache(self):
        cache = Mock()
        character = SimpleNamespace(
            year=2024, num=2, alter="B", name="Test",
            birthday_iso="2000-01-01", origin_age=10, age_str="",
        )
        with patch("character_cache_mgr.CharacterCacheManager", return_value=cache):
            dialog = FolderPropertiesDialog(self.test_folder, char_entry=character)
            dialog._on_mft_scan_ready(5, 8192, 3, 0, 100)

            cache.update_folder.assert_called_once()
            args = cache.update_folder.call_args.args
            self.assertEqual(args[0], str(self.test_folder))
            self.assertEqual(args[2:5], (3, 5, 8192))
            cache.save.assert_called_once()
            dialog.close()

    def test_mft_success_refreshes_existing_overworld_cache(self):
        cache = Mock()
        with patch("overworld_cache_mgr.OverworldCacheManager", return_value=cache):
            dialog = FolderPropertiesDialog(self.test_folder, overworld_year=2025)
            dialog._on_mft_scan_ready(9, 16384, 2, 0, 500)

            cache.update_folder.assert_called_once()
            args = cache.update_folder.call_args.args
            self.assertEqual(args[0], str(self.test_folder))
            self.assertEqual(args[2:4], (9, 16384))
            cache.save.assert_called_once()
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
