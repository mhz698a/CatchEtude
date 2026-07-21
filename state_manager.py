import sys, time, logging, threading, queue
from enum import Enum, auto
from typing import Optional
from pathlib import Path
from collections import deque
from PyQt6 import QtCore

from utils import is_file_locked, is_temporary, flatten_downloads_root, run_in_threadpool
from fallback_utils import safe_move_to_conflicts
from log_mgr import safe_thread_logger

import config
from app_signals_mgr import AppSignals


# -----------------------
# State model
# -----------------------
class State(Enum):
    IDLE = auto()
    FILE_DETECTED = auto()
    USER_DECIDING = auto()
    APPLY_DECISION = auto()
    RESUME_WATCHER = auto()

class QueueProcessorThread(QtCore.QThread):
    def __init__(self, state_manager):
        super().__init__()
        self.state_manager = state_manager

    def run(self):
        self.state_manager._process_queue()

# -----------------------
# StateManager - authoritative control over state and queue
# -----------------------
class StateManager:
    def __init__(self):
        self._state = State.IDLE
        self._q = queue.Queue()
        self._active_file: Optional[Path] = None
        self._lock = threading.RLock()
        self._state_event = threading.Event()
        self._state_event.set()  # inicialmente libre
        self._enqueue_allowed = threading.Event()
        self._enqueue_allowed.set()

        self._pending: set[Path] = set()
        self._queue_list: list[Path] = []
        self._background_moves: set[Path] = set()
        self._is_scanning = False
        self._last_requeue_log = None
        # notifier for UI (Qt signal) will be set externally by AppController
        self.notifier: Optional['AppSignals'] = None
        # thread to process queue. Start it after every synchronization primitive exists.
        self._thread = QueueProcessorThread(self)
        self._thread.start()


    def current_state(self) -> State:
        with self._lock:
            return self._state

    def has_pending_work(self) -> bool:
        """Returns True if there are files in the queue or being processed."""
        with self._lock:
            return bool(self._pending or self._background_moves or self._active_file is not None or not self._q.empty())

    @safe_thread_logger("StateManagerMaintenance")
    def _safe_maintenance_and_flatten(self):
        """Runs flatten_downloads_root and _run_maintenance_scan safely in a daemon thread."""
        try:
            flatten_downloads_root()
        except (FileNotFoundError, PermissionError, OSError) as e:
            logging.warning(f"OS/IO error during flatten_downloads_root: {e}")
        except Exception:
            logging.exception("Flatten downloads failed")

        with self._lock:
            scanning = self._is_scanning
        if not scanning:
            try:
                self._run_maintenance_scan()
            except Exception:
                logging.exception("Maintenance scan failed")

    def _set_state(self, s: State):
        with self._lock:
            logging.info(f"State transition: {self._state} -> {s}")
            self._state = s
            self._state_event.set()

        self._purge_missing_queue_entries()

        # 🔽 NUEVO: cuando el sistema queda libre, aplanar descargas
        if s == State.IDLE:
            try:
                run_in_threadpool(self._safe_maintenance_and_flatten)
            except Exception:
                logging.exception("Failed to start maintenance task in threadpool")

    def can_enqueue(self) -> bool:
        """Watcher reads this: only allow enqueue when NOT in USER_DECIDING."""
        return self.current_state() != State.USER_DECIDING

    def _emit_queue_update(self):
        if self.notifier:
            # Send copy of current queue list and active file path
            active_str = str(self._active_file) if self._active_file else ""
            self.notifier.queue_updated.emit(list(self._queue_list), active_str)

    def _purge_missing_queue_entries(self) -> int:
        removed = 0

        with self._lock:
            active = self._active_file
            kept: list[Path] = []

            for p in self._queue_list:
                if p == active or p.exists():
                    kept.append(p)
                    continue

                removed += 1
                self._pending.discard(p)
                logging.info(f"Removed missing queued file: {p}")

            if removed:
                self._queue_list = kept

                with self._q.mutex:
                    self._q.queue = deque(
                        item for item in self._q.queue
                        if item == active or item.exists()
                    )

                self._emit_queue_update()

                if not self._pending and not self._background_moves and self._active_file is None and self.notifier:
                    self.notifier.queue_empty.emit()

        return removed


    def enqueue_file(self, p: Path):
        # ✅ deduplicación
        if not p.exists():
            logging.debug(f"Skipping missing file before enqueue: {p}")
            return

        with self._lock:
            if p in self._pending or p in self._background_moves:
                logging.debug(f"Already pending: {p}")
                return

            logging.info(f"Enqueueing file: {p}")
            self._pending.add(p)
            self._queue_list.append(p)
            self._q.put(p)
            self._emit_queue_update()

    def enqueue_files(self, paths: list[Path]):
        if not paths:
            return
        with self._lock:
            added = False
            for p in paths:
                if not p.exists():
                    logging.debug(f"Skipping missing file before enqueue: {p}")
                    continue
                if p in self._pending or p in self._background_moves:
                    logging.debug(f"Already pending: {p}")
                    continue

                logging.info(f"Enqueueing file: {p}")
                self._pending.add(p)
                self._queue_list.append(p)
                self._q.put(p)
                added = True
            if added:
                self._emit_queue_update()

    @safe_thread_logger("StateManagerQueueProcessor")
    def _process_queue(self):
        while True:
            try:
                # Wait until system is IDLE
                while self.current_state() != State.IDLE:
                    self._state_event.wait(2)
                    self._state_event.clear()

                p: Path = self._q.get()

                if not p.exists():
                    with self._lock:
                        self._pending.discard(p)
                        if p in self._queue_list:
                            self._queue_list.remove(p)
                        self._emit_queue_update()
                        if not self._pending and not self._background_moves and self._active_file is None and self.notifier:
                            self.notifier.queue_empty.emit()
                    continue

                # Double check IDLE state after popping
                if self.current_state() != State.IDLE:
                    self._q.put(p)
                    continue

                # Prepare for detection
                with self._lock:
                    self._active_file = p
                    self._emit_queue_update()

                self._set_state(State.FILE_DETECTED)

                # Notify UI
                if self.notifier:
                    logging.info(f"Signaling UI for file: {p}")
                    self.notifier.file_detected.emit(str(p))
                else:
                    logging.error("No notifier connected; safe move to conflictos")
                    safe_move_to_conflicts(p)
                    self._active_file = None
                    self._set_state(State.IDLE)

                # Wait until the UI transitions state beyond FILE_DETECTED
                while self.current_state() == State.FILE_DETECTED:
                    self._state_event.wait(1)
                    self._state_event.clear()

            except Exception:
                logging.exception("StateManager queue processing error")
                time.sleep(1)

    def declare_user_deciding(self):
        """Call when UI has been shown and the system must freeze."""
        if self.current_state() not in (State.FILE_DETECTED,):
            logging.error("Invalid transition to USER_DECIDING")
            return False
        self._enqueue_allowed.clear()
        self._set_state(State.USER_DECIDING)
        return True

    def _clear_active_file(self, discard_pending: bool = False) -> Optional[Path]:
        """Clears only the active-file owner fields under lock."""
        with self._lock:
            src = self._active_file
            if src is None:
                return None

            if discard_pending:
                self._pending.discard(src)
            if src in self._queue_list:
                self._queue_list.remove(src)
            self._active_file = None
            self._emit_queue_update()
            return src

    def start_background_move(self, src: Path) -> bool:
        """
        Hands the active file to a background move worker and returns to IDLE.

        The file remains in _pending/_background_moves until the worker reports
        success or failure, so queue_empty and idle checks cannot hide the UI
        while disk I/O is still in flight.
        """
        if self.current_state() != State.USER_DECIDING:
            logging.warning(f"start_background_move called in state {self.current_state()}")
            return False

        with self._lock:
            if self._active_file != src:
                logging.warning(f"start_background_move source mismatch: active={self._active_file}, src={src}")
                return False

            self._background_moves.add(src)
            if src in self._queue_list:
                self._queue_list.remove(src)
            self._active_file = None
            self._emit_queue_update()

        self._set_state(State.IDLE)
        self._enqueue_allowed.set()
        return True

    def fail_background_move(self, src: Path) -> None:
        """Requeues a failed background move without dropping the next active file."""
        with self._lock:
            self._background_moves.discard(src)
            if src.exists():
                if src not in self._pending:
                    self._pending.add(src)
                if src in self._queue_list:
                    self._queue_list.remove(src)
                self._queue_list.insert(0, src)
                with self._q.mutex:
                    self._q.queue.appendleft(src)
                logging.info(f"Requeued failed background move at queue front: {src}")
            else:
                self._pending.discard(src)
                if src in self._queue_list:
                    self._queue_list.remove(src)
                logging.warning(f"Background move failed but source is missing, discarded: {src}")
            self._emit_queue_update()
            is_empty = len(self._pending) == 0 and len(self._background_moves) == 0 and self._active_file is None

        self._state_event.set()
        if is_empty and self.notifier:
            self.notifier.queue_empty.emit()

    def discard_active_file(self):
        """
        Used when a file is deleted or explicitly removed without a move task.
        Discards it from pending and returns to IDLE.
        """
        src = self._clear_active_file(discard_pending=True)
        if src:
            logging.info(f"Discarded active file: {src.name}")
            self._set_state(State.RESUME_WATCHER)
            self._set_state(State.IDLE)
            self._enqueue_allowed.set()

        with self._lock:
            is_empty = len(self._pending) == 0 and len(self._background_moves) == 0
        if is_empty and self.notifier:
            self.notifier.queue_empty.emit()

    def complete_background_move(self, src: Path) -> None:
        """
        Logical bookkeeping only. Removes a completed background move from the queue tracking.
        """
        with self._lock:
            self._background_moves.discard(src)
            self._pending.discard(src)
            if src in self._queue_list:
                self._queue_list.remove(src)
            self._emit_queue_update()
            is_empty = (
                len(self._pending) == 0
                and len(self._background_moves) == 0
                and self._active_file is None
            )
        if is_empty and self.notifier:
            self.notifier.queue_empty.emit()

    def register_undone_file(self, target: Path) -> None:
        """
        Logical bookkeeping only. Handles queue updating (including hot-swap) for an undone file.
        """
        if self.current_state() == State.USER_DECIDING and self._active_file:
            current = self._active_file
            logging.info(f"Undo Hot-Swap: putting {current.name} back to queue, showing {target.name}")
            with self._lock:
                self._q.put(current)
                if current in self._queue_list:
                    self._queue_list.remove(current)
                self._queue_list.insert(0, target)
                self._queue_list.insert(1, current)

                self._active_file = target
                self._pending.add(target)
                self._emit_queue_update()

            self._set_state(State.FILE_DETECTED)
            if self.notifier:
                self.notifier.file_detected.emit(str(target))
        else:
            self.enqueue_file(target)

    def maintenance_tick(self):
        """
        Tareas de mantenimiento que SOLO deben correr cuando el sistema está IDLE.
        """
        try:
            self._purge_missing_queue_entries()

            if self._active_file is not None and not self._active_file.exists():
                self._skip_missing_active_file(
                    f"Archivo faltante omitido: {self._active_file.name}"
                )

            if self.current_state() != State.IDLE:
                return

            run_in_threadpool(self._safe_maintenance_and_flatten)

        except Exception:
            logging.exception("Maintenance tick failed")

    def _run_maintenance_scan(self):
        with self._lock:
            if self._is_scanning: return
            self._is_scanning = True

        try:
            scan_existing_downloads(self)
        finally:
            with self._lock:
                self._is_scanning = False

    def _skip_missing_active_file(self, reason: str = ""):
        p = self._active_file

        if p is not None:
            with self._lock:
                self._pending.discard(p)
                if p in self._queue_list:
                    self._queue_list.remove(p)
                self._active_file = None
                self._emit_queue_update()

        if self.notifier and reason:
            self.notifier.warning_message.emit(reason)

        self._set_state(State.RESUME_WATCHER)
        self._set_state(State.IDLE)
        self._enqueue_allowed.set()

        with self._lock:
            is_empty = len(self._pending) == 0 and len(self._background_moves) == 0
        if is_empty and self.notifier:
            self.notifier.queue_empty.emit()

    def discard_missing_active_file(self, reason: str = "") -> bool:
        if self._active_file is None:
            return False
        self._skip_missing_active_file(reason)
        return True


def scan_existing_downloads(state_manager: StateManager):
    try:
        now = time.time()
        to_enqueue = []
        for p in sorted(config.DOWNLOADS.iterdir()):
            if not p.is_file() or is_temporary(p):
                continue

            try:
                stat = p.stat()
                # If modified within the last 1 second, skip it (will be caught later)
                if now - stat.st_mtime < 1:
                    continue

                if is_file_locked(p):
                    continue

                to_enqueue.append(p)
            except Exception:
                continue
        if to_enqueue:
            state_manager.enqueue_files(to_enqueue)
    except Exception:
        logging.exception("Error during scan_existing_downloads")
