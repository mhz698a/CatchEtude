import os
import sys
import ctypes
import tempfile
import threading
import queue
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Keep Windows-only application imports available in Linux CI.
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

for module_name in ("win32file", "win32con", "win32event", "win32api", "win32process"):
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

from PyQt6 import QtWidgets
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

import config
import file_worker_mgr
import utils
from file_worker_mgr import FileMoveWorker
from pending_dialog import PendingDialog
from queue_rename_dialog import QueueRenameDialog
from state_manager import StateManager, State
import watcher_mgr
from watcher_mgr import WatcherHandler

try:
    from main_window_mgr import MainWindow
except Exception:
    MainWindow = None


class FakeLocalization:
    def get(self, key):
        values = {
            "msg_pending_files_one": "Hay 1 archivo pendiente",
            "msg_pending_files_many": "Hay {count} archivos pendientes",
            "btn_show_again": "Mostrar de nuevo",
        }
        return values.get(key, key)


class TestQueueProgressRegressions(unittest.TestCase):
    def test_double_click_file_is_allowed_when_active_item_is_a_folder(self):
        if MainWindow is None:
            self.skipTest("MainWindow dependencies are unavailable in this environment")

        with tempfile.TemporaryDirectory() as temp:
            active_folder = Path(temp) / "active-folder"
            active_folder.mkdir()
            queued_file = Path(temp) / "queued-file.txt"
            queued_file.write_text("queued")

            class StateStub:
                selected = None

                def select_queued_file(self, path):
                    self.selected = path
                    return True

            stub = type("WindowStub", (), {})()
            stub.filepath = active_folder
            stub.state_manager = StateStub()
            MainWindow._on_queue_file_double_clicked(stub, str(queued_file))
            self.assertEqual(stub.state_manager.selected, queued_file)

    def test_flatten_reports_progress_for_each_file(self):
        original_downloads = config.DOWNLOADS
        original_setctime = utils.setctime_blocking
        try:
            with tempfile.TemporaryDirectory() as temp:
                downloads = Path(temp) / "Downloads"
                downloads.mkdir()
                config.DOWNLOADS = downloads
                utils.setctime_blocking = lambda *args, **kwargs: None

                folder = downloads / "to-flatten"
                folder.mkdir()
                (folder / "one.txt").write_text("one")
                (folder / "two.txt").write_text("two")
                events = []

                moved, success = utils.flatten_single_folder(
                    folder,
                    progress_callback=lambda current, total, path, phase:
                        events.append((current, total, path, phase)),
                )
                self.assertTrue(success)
                self.assertEqual(len(moved), 2)
                move_events = [event for event in events if event[3] == "move"]
                self.assertTrue(move_events)
                self.assertEqual(move_events[-1][:2], (2, 2))
                self.assertTrue(any(event[3] == "scan" for event in events))
        finally:
            config.DOWNLOADS = original_downloads
            utils.setctime_blocking = original_setctime

    def test_pending_dialog_displays_singular_and_plural_count(self):
        dialog = PendingDialog(FakeLocalization(), lambda: None)
        dialog.set_pending_count(3)
        self.assertEqual(dialog.lbl_msg.text(), "Hay 3 archivos pendientes")
        dialog.set_pending_count(1)
        self.assertEqual(dialog.lbl_msg.text(), "Hay 1 archivo pendiente")

    def test_state_manager_exposes_pending_count(self):
        manager = StateManager.__new__(StateManager)
        manager._lock = threading.RLock()
        manager._pending = set()

        with tempfile.TemporaryDirectory() as temp:
            paths = [Path(temp) / "one.txt", Path(temp) / "two.txt"]
            for path in paths:
                path.write_text("queued")
            manager._pending.update(paths)
            self.assertEqual(manager.pending_count(), 2)

    def test_file_move_worker_emits_progress_for_large_undo_transfer(self):
        original_same_drive = file_worker_mgr.is_same_drive
        original_setctime = file_worker_mgr.setctime_blocking
        try:
            file_worker_mgr.is_same_drive = lambda *_args: False
            file_worker_mgr.setctime_blocking = lambda *_args, **_kwargs: None

            with tempfile.TemporaryDirectory() as temp:
                source = Path(temp) / "moved-large.bin"
                destination = Path(temp) / "Downloads" / "moved-large.bin"
                destination.parent.mkdir(parents=True)
                source.write_bytes(b"x" * (3 * 1024 * 1024))
                metadata = {
                    "atime": source.stat().st_atime,
                    "mtime": source.stat().st_mtime,
                    "ctime": source.stat().st_ctime,
                }
                worker = FileMoveWorker(source, destination, restore_meta=metadata)
                progress = []
                finished = []
                worker.progress.connect(progress.append)
                worker.finished.connect(
                    lambda ok, path, message: finished.append((ok, path, message))
                )
                worker.run()

                self.assertTrue(finished and finished[0][0])
                self.assertTrue(destination.is_file())
                self.assertFalse(source.exists())
                self.assertTrue(progress)
                self.assertEqual(progress[-1], 100)
        finally:
            file_worker_mgr.is_same_drive = original_same_drive
            file_worker_mgr.setctime_blocking = original_setctime


    def _make_frozen_queue(self, active_path: Path, queued_paths: list[Path]):
        # Avoid starting QueueProcessorThread: these tests exercise bookkeeping
        # deterministically and must not race a live consumer.
        manager = StateManager.__new__(StateManager)
        manager._state = State.USER_DECIDING
        manager._q = queue.Queue()
        manager._active_file = active_path
        manager._lock = threading.RLock()
        manager._state_event = threading.Event()
        manager._enqueue_allowed = threading.Event()
        manager._pending = {active_path, *queued_paths}
        manager._queue_list = [active_path, *queued_paths]
        manager._queued_rename_positions = {}
        manager._background_moves = set()
        manager._is_scanning = False
        manager.recent_path_handler = None
        manager._last_requeue_log = None
        manager.notifier = None
        with manager._q.not_full:
            manager._q.queue.extend(queued_paths)
            manager._q.unfinished_tasks = len(queued_paths)
        return manager

    def test_renamed_pending_file_returns_to_its_original_queue_index(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            active = root / "active.txt"
            first = root / "first.txt"
            source = root / "queued.txt"
            last = root / "last.txt"
            for path in (active, first, source, last):
                path.write_text(path.name)

            manager = self._make_frozen_queue(active, [first, source, last])
            destination = root / "renamed.txt"

            self.assertTrue(manager.rename_queued_file(source, destination))
            self.assertFalse(source.exists())
            # scan_existing_downloads reinserts stable discoveries in batches.
            manager.enqueue_files([destination])

            with manager._lock:
                self.assertEqual(
                    manager._queue_list,
                    [active, first, destination, last],
                )
                self.assertEqual(
                    list(manager._q.queue),
                    [first, destination, last],
                )
                self.assertEqual(manager.pending_count(), 4)

    def test_renamed_active_file_is_restored_as_active_after_rediscovery(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "active.txt"
            next_file = root / "next.txt"
            source.write_text("active")
            next_file.write_text("next")

            manager = self._make_frozen_queue(source, [next_file])
            destination = root / "active-renamed.txt"

            self.assertTrue(manager.rename_queued_file(source, destination))
            manager.enqueue_file(destination)

            with manager._lock:
                self.assertEqual(manager._active_file, destination)
                self.assertEqual(manager._queue_list, [destination, next_file])
                self.assertEqual(list(manager._q.queue), [next_file])
                self.assertEqual(manager.current_state(), State.FILE_DETECTED)

    def test_queue_rename_dialog_has_600_pixel_width_and_keeps_extension(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "original.mp4"
            source.write_bytes(b"")
            dialog = QueueRenameDialog(source, FakeLocalization())
            self.assertEqual(dialog.width(), 600)
            self.assertEqual(dialog.new_stem, "original")
            self.assertEqual(dialog.extension_label.text(), ".mp4")
            dialog.close()

    def test_watcher_accepts_explicit_candidate_inside_downloads_subfolder(self):
        original_downloads = config.DOWNLOADS
        original_runner = watcher_mgr.run_in_threadpool
        scheduled = []
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp) / "Downloads"
                nested = root / "subfolder"
                nested.mkdir(parents=True)
                candidate = nested / "queued.txt"
                candidate.write_text("queued")
                config.DOWNLOADS = root
                watcher_mgr.run_in_threadpool = (
                    lambda func, *args, **kwargs: scheduled.append((func, args, kwargs))
                )

                handler = WatcherHandler(lambda path: None)
                self.assertTrue(handler.handle_candidate(candidate))
                self.assertEqual(len(scheduled), 1)
        finally:
            config.DOWNLOADS = original_downloads
            watcher_mgr.run_in_threadpool = original_runner


if __name__ == "__main__":
    unittest.main()
