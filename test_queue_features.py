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

# Dynamic mocking of Windows-specific and PyQt6 modules for headless Linux/CI environments
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

try:
    from PyQt6 import QtCore, QtWidgets, QtGui, QtNetwork
    HAS_PYQT = True
except ImportError:
    HAS_PYQT = False

    class MockQt:
        class ItemDataRole:
            UserRole = 0
            UserRolePlusOne = 1

    class MockQtCore:
        Qt = MockQt
        class QThread:
            def __init__(self, parent=None): pass
            def start(self): pass
            def quit(self): pass
            def wait(self): pass
        class QObject:
            def __init__(self, parent=None): pass
        class QRunnable: pass
        class QThreadPool:
            @staticmethod
            def globalInstance():
                return MockQtCore.QThreadPool()
            def start(self, r): pass
        def pyqtSlot(*args, **kwargs):
            return lambda func: func
        def pyqtSignal(*args, **kwargs):
            class MockSignal:
                def connect(self, slot): pass
                def emit(self, *args, **kwargs): pass
            return MockSignal()

    class MockQLocalSocket:
        def __init__(self, parent=None): pass
        def connectToServer(self, name): pass
        def waitForConnected(self, ms): return False
        def write(self, data): pass
        def waitForBytesWritten(self, ms): pass
        def disconnectFromServer(self): pass

    mock_pyqt6 = type('MockPyQt6', (), {
        'QtCore': MockQtCore,
        'QtWidgets': type('MockQtWidgets', (), {}),
        'QtGui': type('MockQtGui', (), {}),
        'QtNetwork': type('MockQtNetwork', (), {
            'QLocalSocket': MockQLocalSocket
        }),
    })
    sys.modules['PyQt6'] = mock_pyqt6
    sys.modules['PyQt6.QtCore'] = MockQtCore
    sys.modules['PyQt6.QtWidgets'] = mock_pyqt6.QtWidgets
    sys.modules['PyQt6.QtGui'] = mock_pyqt6.QtGui
    sys.modules['PyQt6.QtNetwork'] = mock_pyqt6.QtNetwork

from utils import flatten_single_folder
from state_manager import StateManager, State
import config

class TestQueueFeatures(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig_downloads = config.DOWNLOADS
        config.DOWNLOADS = Path(self.tmp_dir) / "Downloads"
        config.DOWNLOADS.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        config.DOWNLOADS = self.orig_downloads

    def test_flatten_folder_success(self):
        folder = config.DOWNLOADS / "FolderToFlatten"
        folder.mkdir()
        file1 = folder / "test1.txt"
        file1.write_text("hello")

        moved, success = flatten_single_folder(folder)
        self.assertTrue(success)
        self.assertEqual(len(moved), 1)
        self.assertFalse(folder.exists())
        self.assertTrue((config.DOWNLOADS / "test1.txt").exists())

    def test_flatten_folder_locked_or_temp_file(self):
        folder = config.DOWNLOADS / "FolderInUse"
        folder.mkdir()
        temp_file = folder / "downloading.tmp"
        temp_file.write_text("partial download")

        moved, success = flatten_single_folder(folder)
        self.assertFalse(success)
        self.assertTrue(folder.exists())

    def test_undo_hot_swap_option_a(self):
        sm = StateManager()
        file_a = config.DOWNLOADS / "file_a.txt"
        file_b = config.DOWNLOADS / "file_b.txt"
        file_c = config.DOWNLOADS / "file_c.txt"

        for f in (file_a, file_b, file_c):
            f.write_text("data")

        sm.enqueue_files([file_b, file_c])
        # Allow queue thread to process file_b or simulate USER_DECIDING
        with sm._lock:
            sm._active_file = file_b
            sm._state = State.USER_DECIDING

        # Register undone file A
        sm.register_undone_file(file_a)

        with sm._lock:
            self.assertEqual(sm._active_file, file_a)
            # File B should be at index 1 of _queue_list and front of _q.queue
            self.assertEqual(sm._queue_list[0], file_a)
            self.assertEqual(sm._queue_list[1], file_b)
            self.assertEqual(sm._q.queue[0], file_b)

    def test_select_queued_file(self):
        sm = StateManager()
        file_1 = config.DOWNLOADS / "file_1.txt"
        file_2 = config.DOWNLOADS / "file_2.txt"
        file_3 = config.DOWNLOADS / "file_3.txt"
        file_4 = config.DOWNLOADS / "file_4.txt"

        for f in (file_1, file_2, file_3, file_4):
            f.write_text("data")

        sm.enqueue_files([file_1, file_2, file_3, file_4])

        with sm._lock:
            sm._active_file = file_1
            sm._state = State.USER_DECIDING

        # Select file_4
        res = sm.select_queued_file(file_4)
        self.assertTrue(res)

        with sm._lock:
            self.assertEqual(sm._active_file, file_4)
            # file_4 active (index 0), file_1 top pending (index 1)
            self.assertEqual(sm._queue_list[0], file_4)
            self.assertEqual(sm._queue_list[1], file_1)
            # Next in queue deque is file_1
            self.assertEqual(sm._q.queue[0], file_1)

    def test_reset_queue_and_rescan(self):
        sm = StateManager()
        file_1 = config.DOWNLOADS / "file_1.txt"
        file_2 = config.DOWNLOADS / "file_2.txt"
        bg_file = config.DOWNLOADS / "bg_file.txt"

        for f in (file_1, file_2, bg_file):
            f.write_text("data")

        sm.enqueue_files([file_1, file_2])
        with sm._lock:
            sm._active_file = file_1
            sm._background_moves.add(bg_file)

        sm.reset_queue_and_rescan()

        with sm._lock:
            # Active file and queue list should have been reset
            self.assertIsNone(sm._active_file)
            self.assertIn(bg_file, sm._background_moves)

if __name__ == "__main__":
    unittest.main()
