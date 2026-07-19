"""
Background Move Manager for CatchEtude.
Handles enqueuing and running multiple background moves with prioritization and concurrency limit.
"""

import logging
from pathlib import Path
from PyQt6 import QtCore
from file_worker_mgr import FileMoveWorker

class BackgroundMoveManager(QtCore.QObject):
    """
    Manages concurrent background file copy/move tasks.
    Allows up to 4 concurrent moves, prioritizing heavier files first.
    """
    move_started = QtCore.pyqtSignal(Path, Path)            # (src, dst)
    move_progress = QtCore.pyqtSignal(Path, int)            # (src, progress)
    # (src, dst, ok, error_msg, src_meta, decision)
    move_finished = QtCore.pyqtSignal(Path, Path, bool, str, dict, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._max_concurrent = 4
        self._pending_tasks = []      # List of dicts: {"src": Path, "dst": Path, "decision": dict, "src_meta": dict, "size": int}
        self._active_workers = {}     # Maps src Path to (worker, thread)

    def enqueue_move(self, src: Path, dst: Path, decision: dict, src_meta: dict):
        """Enqueues a new file move task."""
        # Get file size for prioritization (default to 0 if error)
        try:
            size = src.stat().st_size
        except Exception:
            size = 0

        task = {
            "src": src,
            "dst": dst,
            "decision": decision,
            "src_meta": src_meta,
            "size": size
        }

        # Check if already active or pending
        if src in self._active_workers or any(t["src"] == src for t in self._pending_tasks):
            logging.info(f"Move task for {src} already active or enqueued.")
            return

        self._pending_tasks.append(task)
        logging.info(f"Enqueued background move: {src} -> {dst} (Size: {size} bytes)")

        # Prioritize heavier files first
        self._pending_tasks.sort(key=lambda x: x["size"], reverse=True)

        # Process the queue
        self._process_queue()

    def active_count(self) -> int:
        """Returns the number of currently running transfers."""
        return len(self._active_workers)

    def is_idle(self) -> bool:
        """Returns True if there are no running or pending moves."""
        return len(self._active_workers) == 0 and len(self._pending_tasks) == 0

    def _process_queue(self):
        """Starts enqueued tasks if concurrency limit permits."""
        while len(self._active_workers) < self._max_concurrent and self._pending_tasks:
            task = self._pending_tasks.pop(0)
            src = task["src"]
            dst = task["dst"]
            decision = task["decision"]
            src_meta = task["src_meta"]

            logging.info(f"Starting prioritized background move: {src} -> {dst}")

            thread = QtCore.QThread(self)
            worker = FileMoveWorker(src, dst)
            worker.moveToThread(thread)

            self._active_workers[src] = (worker, thread)

            # Connect signals
            thread.started.connect(worker.run)
            worker.progress.connect(lambda val, s=src: self.move_progress.emit(s, val))

            # Helper closure to capture variables cleanly
            def make_on_finished(s=src, d=dst, meta=src_meta, dec=decision, w=worker, t=thread):
                def on_finished(ok: bool, copied_path: Path, msg: str):
                    logging.info(f"Finished background move {s}: ok={ok}, msg={msg}")

                    # Clean up worker and thread
                    self._active_workers.pop(s, None)
                    t.quit()
                    t.wait()
                    w.deleteLater()
                    t.deleteLater()

                    # Emit result signal
                    self.move_finished.emit(s, d, ok, msg, meta, dec)

                    # Trigger next queue item
                    self._process_queue()
                return on_finished

            worker.finished.connect(make_on_finished())

            # Emit started signal so UI can show the item immediately
            self.move_started.emit(src, dst)

            # Start thread
            thread.start()
