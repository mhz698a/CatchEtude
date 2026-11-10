import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ntfs_mft.scanner import MFTScanResult, MFTScanner


class _FakeVolumeApi:
    def get_volume_info(self, _path):
        return SimpleNamespace(filesystem="NTFS")

    def is_process_elevated(self):
        return True

    def get_file_reference(self, _path):
        return 1

    def open_file_hint(self, _path):
        return "directory-hint"

    def open_volume(self, _volume):
        return "volume-handle"

    def close_handle(self, _handle):
        pass


class _TrackedConnection:
    def __init__(self, connection, state):
        self._connection = connection
        self._state = state

    def __getattr__(self, name):
        return getattr(self._connection, name)

    def close(self):
        try:
            self._connection.close()
        finally:
            self._state["closed"] = True


class TestMFTSQLiteCleanup(unittest.TestCase):
    def test_database_connection_closes_before_temporary_directory_cleanup(self):
        real_connect = sqlite3.connect
        real_temporary_directory = tempfile.TemporaryDirectory
        state = {"closed": False, "temporary_path": None}

        def tracked_connect(*args, **kwargs):
            return _TrackedConnection(real_connect(*args, **kwargs), state)

        class GuardedTemporaryDirectory:
            def __init__(self, *args, **kwargs):
                self._manager = real_temporary_directory(*args, **kwargs)

            def __enter__(self):
                path = self._manager.__enter__()
                state["temporary_path"] = Path(path)
                return path

            def __exit__(self, exc_type, exc_value, traceback):
                was_closed_before_cleanup = state["closed"]
                try:
                    return self._manager.__exit__(exc_type, exc_value, traceback)
                finally:
                    if not was_closed_before_cleanup:
                        raise AssertionError(
                            "SQLite connection remained open when the MFT temp folder was removed"
                        )

        expected = MFTScanResult(
            file_count=3,
            total_size=1024,
            root_entry_count=2,
            inaccessible_count=0,
            records_scanned=12,
        )
        scanner = MFTScanner(api=_FakeVolumeApi())

        with tempfile.TemporaryDirectory() as workspace:
            folder = Path(workspace) / "target"
            folder.mkdir()

            with patch(
                "ntfs_mft.scanner.sqlite3.connect", side_effect=tracked_connect
            ), patch(
                "ntfs_mft.scanner.tempfile.TemporaryDirectory",
                side_effect=GuardedTemporaryDirectory,
            ), patch.object(
                scanner, "_index_volume", return_value=12
            ), patch.object(
                scanner, "_scan_index", return_value=expected
            ):
                result = scanner.scan_folder(folder)

        self.assertEqual(result, expected)
        self.assertTrue(state["closed"])
        self.assertIsNotNone(state["temporary_path"])
        self.assertFalse(state["temporary_path"].exists())


if __name__ == "__main__":
    unittest.main()
