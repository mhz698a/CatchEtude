import unittest
import sys
from pathlib import Path
import tempfile
import shutil

# Mock ctypes windll and WinDLL for Linux/CI environment
import ctypes
if not hasattr(ctypes, 'windll'):
    class MockWinDLL:
        def __getattr__(self, name):
            class MockDLL:
                def __getattr__(self, func):
                    return lambda *args, **kwargs: 1
            return MockDLL()
    ctypes.windll = MockWinDLL()
    ctypes.WinDLL = lambda name: MockWinDLL()

# Dynamic mocking of Windows-specific modules for headless Linux environments
try:
    import win32file
except ImportError:
    sys.modules['win32file'] = type('MockWin32File', (), {})
    sys.modules['win32con'] = type('MockWin32Con', (), {})
    sys.modules['pywintypes'] = type('MockPyWinTypes', (), {
        'error': Exception
    })

try:
    import send2trash
except ImportError:
    sys.modules['send2trash'] = type('MockSend2Trash', (), {
        'send2trash': lambda x: True
    })

import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6 import QtWidgets
from state_manager import StateManager
from plugins.divition_subfolder_plugin import SplitFolderWorker, SplitFolderDialog

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)


class TestQueueAndDivisionFeatures(unittest.TestCase):

    def test_queue_reordering(self):
        sm = StateManager()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            f1 = tmp / "file1.txt"
            f2 = tmp / "file2.txt"
            f3 = tmp / "file3.txt"
            f4 = tmp / "file4.txt"
            for f in (f1, f2, f3, f4):
                f.write_text("content")

            sm.enqueue_files([f1, f2, f3, f4])
            # Active file is f1
            sm._active_file = f1

            # Current queue list: [f1, f2, f3, f4]
            self.assertEqual(sm._queue_list, [f1, f2, f3, f4])

            # Send f4 to top (should be placed right after active f1)
            res = sm.move_queued_file_to_top(f4)
            self.assertTrue(res)
            self.assertEqual(sm._queue_list, [f1, f4, f2, f3])

            # Send f4 to bottom
            res = sm.move_queued_file_to_bottom(f4)
            self.assertTrue(res)
            self.assertEqual(sm._queue_list, [f1, f2, f3, f4])

    def test_split_folder_dialog_calc(self):
        # < 100 files -> min 2, max 4
        dlg_small = SplitFolderDialog(total_files=80)
        self.assertEqual(dlg_small.min_parts, 2)
        self.assertEqual(dlg_small.max_parts, 4)

        # >= 100 files -> min 2, max total_files // 50
        dlg_large = SplitFolderDialog(total_files=250)
        self.assertEqual(dlg_large.min_parts, 2)
        self.assertEqual(dlg_large.max_parts, 5)

    def test_split_folder_worker(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            target_dir = Path(tmpdir) / "SerieA"
            target_dir.mkdir()

            # Create 10 dummy files
            for i in range(10):
                (target_dir / f"file_{i:02d}.txt").write_text("hello")

            worker = SplitFolderWorker(target_dir, parts_count=3)

            results = []
            worker.finished_signal.connect(lambda ok, msg: results.append((ok, msg)))
            worker.run()

            self.assertEqual(len(results), 1)
            self.assertTrue(results[0][0])

            # Check subfolders
            part0 = Path(tmpdir) / "SerieA_000"
            part1 = Path(tmpdir) / "SerieA_001"
            part2 = Path(tmpdir) / "SerieA_002"

            self.assertTrue(part0.exists())
            self.assertTrue(part1.exists())
            self.assertTrue(part2.exists())

            # 10 files split across 3 parts -> 4, 3, 3 files
            self.assertEqual(len(list(part0.iterdir())), 4)
            self.assertEqual(len(list(part1.iterdir())), 3)
            self.assertEqual(len(list(part2.iterdir())), 3)

            # Original folder remains empty
            self.assertEqual(len(list(target_dir.iterdir())), 0)


if __name__ == "__main__":
    unittest.main()
