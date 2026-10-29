"""
Watch Downloads for newly created or renamed files and queue them once stable.

The Qt application owns WatcherThread; watchdog owns its filesystem observer;
candidate stability checks run in the shared worker pool.
"""

import logging
import threading
import time
from pathlib import Path

from PyQt6 import QtCore
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import config
from log_mgr import safe_thread_logger
from utils import folder_is_safe_to_flatten, is_file_locked, is_temporary, run_in_threadpool


logger = logging.getLogger(__name__)
_STABILITY_INTERVAL_SECONDS = 1.0
_OBSERVER_RETRY_SECONDS = 2.0


class WatcherHandler(FileSystemEventHandler):
    """Filter Downloads events and submit each candidate only once at a time."""

    def __init__(self, enqueue_callback):
        super().__init__()
        self.enqueue = enqueue_callback
        self._monitoring: set[str] = set()
        self._lock = threading.Lock()

    def on_created(self, event) -> None:
        self.handle_candidate(event.src_path)

    def on_moved(self, event) -> None:
        # Downloads commonly write a temporary file and rename it to its final name.
        self.handle_candidate(event.dest_path)

    def on_modified(self, event) -> None:
        # A later write event can recover a path after a transient access error.
        if not event.is_directory:
            self.handle_candidate(event.src_path)

    def handle_candidate(self, path: str | Path) -> bool:
        """Validate a path and schedule background stability checks."""
        candidate = Path(path)
        try:
            root = Path(config.DOWNLOADS).resolve()
            if candidate.parent.resolve() != root:
                return False
        except OSError:
            logger.debug("Could not resolve candidate path %s", candidate, exc_info=True)
            return False

        if is_temporary(candidate):
            logger.debug("Ignoring temporary download candidate: %s", candidate.name)
            return False
        if not candidate.exists():
            return False

        try:
            key = str(candidate.resolve()).casefold()
        except OSError:
            key = str(candidate.absolute()).casefold()

        with self._lock:
            if key in self._monitoring:
                return False
            self._monitoring.add(key)

        try:
            run_in_threadpool(self._monitor_file, candidate, key)
            return True
        except Exception:
            with self._lock:
                self._monitoring.discard(key)
            logger.exception("Could not schedule download stability check for %s", candidate)
            return False

    def _monitor_file(self, candidate: Path, key: str) -> None:
        """Wait in the worker pool until a file or safe folder is ready to enqueue."""
        try:
            logger.info("Monitoring download candidate: %s", candidate.name)

            while candidate.exists():
                try:
                    if candidate.is_dir():
                        if folder_is_safe_to_flatten(candidate):
                            self.enqueue(candidate)
                            return
                        time.sleep(_STABILITY_INTERVAL_SECONDS)
                        continue

                    before = candidate.stat()
                    time.sleep(_STABILITY_INTERVAL_SECONDS)
                    if not candidate.exists():
                        return

                    after = candidate.stat()
                    unchanged = (
                        before.st_size == after.st_size
                        and before.st_mtime_ns == after.st_mtime_ns
                    )
                    if unchanged:
                        if is_file_locked(candidate):
                            logger.debug(
                                "Download is stable but still locked: %s",
                                candidate.name,
                            )
                            time.sleep(_STABILITY_INTERVAL_SECONDS)
                            continue

                        logger.info(
                            "Download is stable and unlocked: %s (%s bytes)",
                            candidate.name,
                            after.st_size,
                        )
                        self.enqueue(candidate)
                        return

                    logger.debug("Download is still changing: %s", candidate.name)

                except FileNotFoundError:
                    return
                except PermissionError as exc:
                    # Transient Windows access-denied errors must not permanently drop a download.
                    logger.debug("Temporary access error for %s: %s", candidate, exc)
                    time.sleep(_STABILITY_INTERVAL_SECONDS)
                except OSError as exc:
                    logger.warning("Filesystem error while monitoring %s: %s", candidate, exc)
                    time.sleep(_STABILITY_INTERVAL_SECONDS)

        except Exception:
            logger.exception("Error monitoring download candidate %s", candidate)
        finally:
            with self._lock:
                self._monitoring.discard(key)


class WatcherThread(QtCore.QThread):
    """Keep a watchdog observer attached to Downloads, retrying if it stops."""

    def __init__(self, enqueue_callback, parent=None):
        super().__init__(parent)
        self.enqueue_callback = enqueue_callback
        self.observer: Observer | None = None
        self.handler: WatcherHandler | None = None
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()
        self._state_lock = threading.Lock()
        self._pending_candidates: set[Path] = set()

    @property
    def is_watching(self) -> bool:
        return self._ready_event.is_set()

    def watch_candidate(self, path: str | Path) -> bool:
        """Hand a scan-discovered candidate to watchdog's stability monitor."""
        candidate = Path(path)
        with self._state_lock:
            handler = self.handler
            if handler is None:
                self._pending_candidates.add(candidate)
                return False
        return handler.handle_candidate(candidate)

    @safe_thread_logger("WatcherObserver")
    def run(self) -> None:
        while not self._stop_event.is_set():
            observer = None
            handler = None
            try:
                Path(config.DOWNLOADS).mkdir(parents=True, exist_ok=True)
                observer = Observer()
                handler = WatcherHandler(self.enqueue_callback)
                observer.schedule(handler, str(config.DOWNLOADS), recursive=False)
                if self._stop_event.is_set():
                    break
                observer.start()

                with self._state_lock:
                    self.observer = observer
                    self.handler = handler
                    pending = list(self._pending_candidates)
                    self._pending_candidates.clear()
                self._ready_event.set()

                logger.info("Watching Downloads directory: %s", config.DOWNLOADS)
                for candidate in pending:
                    handler.handle_candidate(candidate)

                while observer.is_alive() and not self._stop_event.wait(1.0):
                    pass

                if not self._stop_event.is_set():
                    logger.warning("Downloads observer stopped unexpectedly; restarting it")

            except Exception:
                logger.exception("Could not start or maintain the Downloads observer")

            finally:
                self._ready_event.clear()
                with self._state_lock:
                    if self.observer is observer:
                        self.observer = None
                    if self.handler is handler:
                        self.handler = None
                if observer is not None and observer.ident is not None:
                    try:
                        observer.stop()
                    except Exception:
                        logger.debug("Observer stop failed during cleanup", exc_info=True)
                    try:
                        observer.join(timeout=3.0)
                    except Exception:
                        logger.debug("Observer join failed during cleanup", exc_info=True)

            if not self._stop_event.is_set():
                self._stop_event.wait(_OBSERVER_RETRY_SECONDS)

    def stop(self) -> None:
        """Request shutdown and detach the watchdog observer safely."""
        self._stop_event.set()
        self._ready_event.clear()
        with self._state_lock:
            observer = self.observer
        if observer is None:
            return
        try:
            observer.stop()
        except Exception:
            logger.debug("Observer stop request failed", exc_info=True)
        if observer.ident is not None:
            try:
                observer.join(timeout=3.0)
            except Exception:
                logger.debug("Observer join during shutdown failed", exc_info=True)
