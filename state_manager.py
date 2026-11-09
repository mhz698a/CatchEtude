import os, sys, time, logging, threading, queue
from enum import Enum, auto
from typing import Optional
from pathlib import Path
from collections import deque
from PyQt6 import QtCore

from utils import is_file_locked, is_temporary, folder_is_safe_to_flatten, run_in_threadpool
from fallback_utils import safe_move_to_conflicts
from log_mgr import safe_thread_logger

import config
from app_signals_mgr import AppSignals


# -----------------------
# State model
# -----------------------
class State(Enum):
    """Lifecycle states for the download decision pipeline.

    IDLE:
        No file is currently being shown to the user. The queue processor may
        dequeue the next pending file, maintenance can run, and the watcher may
        enqueue new files.
    FILE_DETECTED:
        A file has been selected from the queue and emitted to the UI, but the
        UI has not yet acknowledged that the user-decision panel is ready.
    USER_DECIDING:
        The active file is visible in the UI and waiting for the user's action;
        automatic queue advancement is paused so the active file is stable.
    APPLY_DECISION:
        Reserved transition state for applying a user decision. The current
        implementation hands moves directly to background workers, but the enum
        value is kept for compatibility with existing state checks.
    RESUME_WATCHER:
        Short-lived state used after discard/delete style actions to resume
        normal watcher/queue processing before returning to IDLE.
    """
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
        # Destination path -> (old path, original queue index), consumed on rediscovery.
        self._queued_rename_positions: dict[str, tuple[Path, int]] = {}
        self._background_moves: set[Path] = set()
        self._is_scanning = False
        # Optional callback installed by the Downloads watcher for unstable entries.
        self.recent_path_handler = None
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

    def pending_count(self) -> int:
        """Return the number of tracked files still waiting for completion."""
        with self._lock:
            return len(self._pending)

    @safe_thread_logger("StateManagerMaintenance")
    def _safe_maintenance_and_flatten(self):
        """Runs _run_maintenance_scan safely in a daemon thread."""
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

    @staticmethod
    def _queue_rename_key(path: Path) -> str:
        """Return a Windows-case-insensitive key for a queued rename destination."""
        return os.path.normcase(os.path.abspath(str(path))).casefold()

    def rename_queued_file(self, source: Path, destination: Path) -> bool:
        """Rename a queued file while preserving its current queue index for rediscovery."""
        source = Path(source)
        destination = Path(destination)

        if not source.is_file():
            raise FileNotFoundError(source)
        if source.parent != destination.parent:
            raise ValueError("Queued files can only be renamed in their current folder.")

        with self._lock:
            if source == self._active_file:
                original_index = (
                    self._queue_list.index(source) if source in self._queue_list else 0
                )
            else:
                if source not in self._queue_list:
                    return False
                # Prevent a race with QueueProcessorThread after it has popped the item
                # but before it has assigned _active_file.
                with self._q.mutex:
                    if source not in self._q.queue:
                        return False
                original_index = self._queue_list.index(source)

            same_windows_path = (
                self._queue_rename_key(source) == self._queue_rename_key(destination)
            )
            if destination.exists() and not same_windows_path:
                raise FileExistsError(destination)
            if same_windows_path and source.name == destination.name:
                return False

            # File.rename is a same-directory metadata operation. Keep the queue lock
            # while it runs so the processor cannot take the old path mid-rename.
            source.rename(destination)
            self._queued_rename_positions[
                self._queue_rename_key(destination)
            ] = (source, original_index)

            logging.info(
                "Renamed queued file; awaiting scanner reinsertion at index %s: %s -> %s",
                original_index,
                source,
                destination,
            )
            return True

    def _enqueue_path_locked(self, path: Path) -> tuple[bool, bool]:
        """Insert a scanner result, restoring a renamed file's original queue index."""
        path = Path(path)
        if not path.exists() or path in self._background_moves:
            return False, False

        rename_info = self._queued_rename_positions.pop(
            self._queue_rename_key(path), None
        )
        if rename_info is None:
            if path in self._pending:
                return False, False
            self._pending.add(path)
            self._queue_list.append(path)
            self._q.put(path)
            self._emit_queue_update()
            return True, False

        previous_path, original_index = rename_info
        was_active = self._active_file == previous_path

        if previous_path in self._queue_list:
            self._queue_list.remove(previous_path)
        if path in self._queue_list:
            self._queue_list.remove(path)
        self._pending.discard(previous_path)
        self._pending.add(path)

        insert_index = min(max(original_index, 0), len(self._queue_list))
        self._queue_list.insert(insert_index, path)

        with self._q.not_full:
            old_was_queued = previous_path in self._q.queue
            new_was_queued = path in self._q.queue
            if old_was_queued:
                self._q.queue.remove(previous_path)
            if new_was_queued:
                self._q.queue.remove(path)

            if was_active:
                # The file being displayed was renamed. Make the rediscovered path
                # active again so MainWindow refreshes its file panel.
                self._active_file = path
            else:
                active_offset = (
                    1
                    if self._active_file is not None
                    and self._active_file in self._queue_list
                    else 0
                )
                queue_index = min(
                    max(insert_index - active_offset, 0),
                    len(self._q.queue),
                )
                self._q.queue.insert(queue_index, path)
                if not old_was_queued and not new_was_queued:
                    self._q.unfinished_tasks += 1
                self._q.not_empty.notify()

        self._emit_queue_update()
        return True, was_active

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
        if not p.exists():
            logging.debug("Skipping missing file before enqueue: %s", p)
            return

        with self._lock:
            added, replaced_active = self._enqueue_path_locked(Path(p))

        if replaced_active:
            self._set_state(State.FILE_DETECTED)
            if self.notifier:
                self.notifier.file_detected.emit(str(p))

    def enqueue_files(self, paths: list[Path]):
        if not paths:
            return

        replaced_active_path = None
        with self._lock:
            for path in paths:
                if not Path(path).exists():
                    logging.debug("Skipping missing file before enqueue: %s", path)
                    continue
                added, replaced_active = self._enqueue_path_locked(Path(path))
                if replaced_active:
                    replaced_active_path = Path(path)

        if replaced_active_path is not None:
            self._set_state(State.FILE_DETECTED)
            if self.notifier:
                self.notifier.file_detected.emit(str(replaced_active_path))

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

    def start_all_background_moves(self) -> list[Path]:
        """Hand every queued file to background workers as one atomic batch.

        This is used by the explicit ``All Queue`` keep option.  Removing every
        source from the processor queue before returning to ``IDLE`` prevents a
        second file from being presented to the user while it is already queued
        for its keep operation.
        """
        if self.current_state() != State.USER_DECIDING:
            logging.warning(
                "start_all_background_moves called in state %s", self.current_state()
            )
            return []

        with self._lock:
            sources = [
                path for path in self._queue_list
                if path == self._active_file or path in self._pending
            ]
            if not sources:
                return []

            self._background_moves.update(sources)
            self._queue_list = [path for path in self._queue_list if path not in sources]
            with self._q.mutex:
                self._q.queue = deque(path for path in self._q.queue if path not in sources)
            self._active_file = None
            self._emit_queue_update()

        self._set_state(State.IDLE)
        self._enqueue_allowed.set()
        return sources

    def reserve_selected_background_moves(self, selected_sources: list[Path]) -> list[Path]:
        """Reserve selected queue files for a batch move without resuming the queue yet.

        The active file must be selected. The caller must enqueue a background task
        for every returned source and then call finish_selected_background_moves().
        """
        if self.current_state() != State.USER_DECIDING:
            logging.warning(
                "reserve_selected_background_moves called in state %s",
                self.current_state(),
            )
            return []

        selected = set(selected_sources)
        with self._lock:
            active = self._active_file
            if active is None or active not in selected:
                return []

            sources = [
                path for path in self._queue_list
                if path in selected and (path == active or path in self._pending)
            ]
            if active not in sources:
                return []

            self._background_moves.update(sources)
            self._queue_list = [path for path in self._queue_list if path not in sources]
            with self._q.mutex:
                self._q.queue = deque(path for path in self._q.queue if path not in sources)
            self._active_file = None
            self._emit_queue_update()

        return sources

    def finish_selected_background_moves(self) -> bool:
        """Resume queue processing after the selected files have been handed to workers."""
        with self._lock:
            if self._state != State.USER_DECIDING or self._active_file is not None:
                logging.warning(
                    "finish_selected_background_moves called from an unexpected queue state"
                )
                return False

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

    def discard_queued_files(self, sources: list[Path]) -> bool:
        """Remove deleted files from the queue, including the active item when selected."""
        if self.current_state() != State.USER_DECIDING:
            logging.warning(
                "discard_queued_files called in state %s", self.current_state()
            )
            return False

        selected = set(sources)
        if not selected:
            return False

        with self._lock:
            active = self._active_file
            removable = {
                path for path in selected
                if path == active or path in self._pending
            }
            if not removable:
                return False

            self._pending.difference_update(removable)
            self._queue_list = [
                path for path in self._queue_list if path not in removable
            ]
            with self._q.mutex:
                self._q.queue = deque(
                    path for path in self._q.queue if path not in removable
                )

            active_removed = active in removable
            if active_removed:
                self._active_file = None

            self._emit_queue_update()

        if active_removed:
            self._set_state(State.RESUME_WATCHER)
            self._set_state(State.IDLE)
            self._enqueue_allowed.set()

        with self._lock:
            is_empty = (
                not self._pending
                and not self._background_moves
                and self._active_file is None
            )

        if is_empty and self.notifier:
            self.notifier.queue_empty.emit()

        return active_removed

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
                with self._q.mutex:
                    if current in self._q.queue:
                        self._q.queue.remove(current)
                    self._q.queue.appendleft(current)

                if current in self._queue_list:
                    self._queue_list.remove(current)
                if target in self._queue_list:
                    self._queue_list.remove(target)

                self._queue_list.insert(0, target)
                self._queue_list.insert(1, current)

                self._active_file = target
                self._pending.add(target)
                self._pending.add(current)
                self._emit_queue_update()

            self._set_state(State.FILE_DETECTED)
            if self.notifier:
                self.notifier.file_detected.emit(str(target))
        else:
            with self._lock:
                if target not in self._pending and target not in self._background_moves:
                    self._pending.add(target)
                    if target in self._queue_list:
                        self._queue_list.remove(target)
                    self._queue_list.insert(0, target)
                    with self._q.mutex:
                        if target in self._q.queue:
                            self._q.queue.remove(target)
                        self._q.queue.appendleft(target)
                    self._emit_queue_update()

    def select_queued_file(self, target: Path) -> bool:
        """
        Switches the currently active file to a user-selected queued file.
        The previously active file remains at the top of the pending queue.
        """
        if not target.exists():
            logging.warning(f"Cannot select missing queued file: {target}")
            return False

        with self._lock:
            if self._active_file == target:
                return True

            current = self._active_file

            with self._q.mutex:
                if target in self._q.queue:
                    self._q.queue.remove(target)
                if current and current.exists():
                    if current in self._q.queue:
                        self._q.queue.remove(current)
                    self._q.queue.appendleft(current)

            if target in self._queue_list:
                self._queue_list.remove(target)
            if current and current in self._queue_list:
                self._queue_list.remove(current)

            self._queue_list.insert(0, target)
            if current:
                self._queue_list.insert(1, current)
                self._pending.add(current)

            self._active_file = target
            self._pending.add(target)
            self._emit_queue_update()

        self._set_state(State.FILE_DETECTED)
        if self.notifier:
            self.notifier.file_detected.emit(str(target))
        return True

    def move_queued_file_to_top(self, target: Path) -> bool:
        """
        Moves a pending file to the top of the pending queue (right after the active file).
        """
        with self._lock:
            if not target.exists() or target == self._active_file or target not in self._queue_list:
                return False

            self._queue_list.remove(target)
            insert_idx = 1 if (self._active_file and self._active_file in self._queue_list) else 0
            self._queue_list.insert(insert_idx, target)

            with self._q.mutex:
                if target in self._q.queue:
                    self._q.queue.remove(target)
                    self._q.queue.appendleft(target)

            self._emit_queue_update()
            return True

    def move_queued_file_to_bottom(self, target: Path) -> bool:
        """
        Moves a file to the end of the queue.
        If target is the currently active file and there are other items in the queue,
        the next item becomes active and the target is moved to the bottom.
        """
        with self._lock:
            if not target.exists() or target not in self._queue_list:
                return False

            if len(self._queue_list) <= 1:
                return False

            if target == self._active_file:
                # Active file is index 0
                next_file = self._queue_list[1]

                self._queue_list.remove(target)
                self._queue_list.append(target)

                with self._q.mutex:
                    if target in self._q.queue:
                        self._q.queue.remove(target)
                    self._q.queue.append(target)

                    if next_file in self._q.queue:
                        self._q.queue.remove(next_file)

                self._active_file = next_file
                self._emit_queue_update()

                self._set_state(State.FILE_DETECTED)
                if self.notifier:
                    self.notifier.file_detected.emit(str(next_file))
                return True
            else:
                self._queue_list.remove(target)
                self._queue_list.append(target)

                with self._q.mutex:
                    if target in self._q.queue:
                        self._q.queue.remove(target)
                        self._q.queue.append(target)

                self._emit_queue_update()
                return True

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

    def reset_queue_and_rescan(self):
        """
        Resets the download queue and active file, then rescans the Downloads folder.
        Preserves active background file moves.
        """
        logging.info("Resetting queue and rescanning downloads folder...")
        with self._lock:
            self._pending.clear()
            self._queue_list.clear()
            with self._q.mutex:
                self._q.queue.clear()
            self._active_file = None
            self._emit_queue_update()

        self._set_state(State.RESUME_WATCHER)
        self._set_state(State.IDLE)
        self._enqueue_allowed.set()

        run_in_threadpool(self._run_maintenance_scan)


def scan_existing_downloads(state_manager: StateManager):
    """
    Enqueue stable Downloads entries and send recent/locked candidates to the watcher.

    This function runs in a worker. Recent files may still be receiving data, so
    the watcher waits for size/mtime stability before adding them to the queue.
    """
    recent_path_handler = getattr(state_manager, "recent_path_handler", None)
    try:
        now = time.time()
        to_enqueue = []

        for path in sorted(config.DOWNLOADS.iterdir(), key=lambda item: item.name.casefold()):
            try:
                if is_temporary(path):
                    continue

                if path.is_dir():
                    if folder_is_safe_to_flatten(path):
                        to_enqueue.append(path)
                    elif recent_path_handler:
                        recent_path_handler(path)
                    continue

                if not path.is_file():
                    continue

                stat = path.stat()
                is_recent = now - stat.st_mtime < 1
                is_locked = is_file_locked(path)
                if is_recent or is_locked:
                    if recent_path_handler:
                        recent_path_handler(path)
                    continue

                to_enqueue.append(path)

            except FileNotFoundError:
                # Entries may be renamed, moved, or deleted while the scan is running.
                continue
            except PermissionError:
                logging.debug("Temporary access error while scanning %s", path, exc_info=True)
                if recent_path_handler:
                    recent_path_handler(path)
            except OSError:
                logging.exception("Error inspecting Downloads entry %s", path)

        if to_enqueue:
            state_manager.enqueue_files(to_enqueue)
            logging.info("Downloads scan queued %s stable entries", len(to_enqueue))

    except FileNotFoundError:
        logging.warning("Downloads directory does not exist: %s", config.DOWNLOADS)
    except Exception:
        logging.exception("Error during scan_existing_downloads")
