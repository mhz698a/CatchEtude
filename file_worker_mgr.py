"""
File Worker module - Handles background file operations.
Módulo File Worker: gestiona las operaciones de archivos en segundo plano.
"""

import os
import shutil
import logging
import time
import threading
from pathlib import Path
from PyQt6.QtCore import QRunnable, QObject, pyqtSignal
from utils import is_same_drive, safe_unlink
from wctime import setctime_blocking
from log_mgr import safe_thread_logger


class FileMoveSignals(QObject):
    """
    Dedicated QObject subclass to hold signals for FileMoveWorker.
    """
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, Path, str)


class FileMoveWorker(QRunnable):
    """
    Worker that performs a file copy with progress reporting, subclassing QRunnable.
    """
    def __init__(self, src: Path, dst: Path):
        super().__init__()
        self.src = src
        self.dst = dst
        self.signals = FileMoveSignals()
        try:
            self.stat = self.src.stat()
        except Exception:
            self.stat = None

    @property
    def progress(self):
        return self.signals.progress

    @property
    def finished(self):
        return self.signals.finished

    def _restore_creation_time_in_helper_thread(self):
        """Restores creation time in a dedicated helper thread.

        The move worker already runs outside the UI thread, but creation-time changes
        call Win32 through ctypes. Keeping that call in a short-lived helper thread
        prevents the QRunnable from directly owning the native call stack and gives
        the worker a bounded wait path for recoverable Win32 errors.
        """
        result = {"error": None}

        def target():
            try:
                setctime_blocking(
                    str(self.dst),
                    getattr(self.stat, "st_birthtime", self.stat.st_ctime),
                )
            except Exception as exc:
                result["error"] = exc

        thread = threading.Thread(
            target=target,
            name=f"ctime-restore-{self.dst.name[:32]}",
            daemon=True,
        )
        thread.start()
        thread.join()

        if result["error"] is not None:
            raise result["error"]

    def _restore_timestamps(self):
        """Restores source timestamps on the destination as part of the move operation."""
        os.utime(
            self.dst,
            (self.stat.st_atime, self.stat.st_mtime)
        )
        self._restore_creation_time_in_helper_thread()

    def _emit_progress(self, pct: int, state: dict) -> None:
        """Throttles progress signals to avoid flooding Qt's event queue."""
        pct = max(0, min(100, int(pct)))
        now = time.monotonic()
        if (
            pct == 100
            or pct >= state["last_pct"] + 1
            or now - state["last_emit"] >= 0.1
        ):
            state["last_pct"] = pct
            state["last_emit"] = now
            self.progress.emit(pct)

    @safe_thread_logger("FileMoveWorker")
    def run(self):
        """Executes the copy operation."""
        try:
            logging.info(f"[FileMoveWorker] Transfer started: '{self.src}' -> '{self.dst}'")
            if not self.stat:
                self.stat = self.src.stat()

            # Ensure destination directory exists
            self.dst.parent.mkdir(parents=True, exist_ok=True)

            if is_same_drive(self.src, self.dst):
                logging.info(f"[FileMoveWorker] Same-drive detected: performing fast atomic move for '{self.src.name}'")
                shutil.move(str(self.src), str(self.dst))

                try:
                    self._restore_timestamps()
                except Exception as ts_err:
                    logging.exception(f"[FileMoveWorker] Timestamp restore failed for '{self.dst}': {ts_err}")
                    self.finished.emit(False, self.dst, "TIMESTAMP_RESTORE_FAILED")
                    return

                self.progress.emit(100)
                logging.info(f"[FileMoveWorker] Same-drive move completed successfully for '{self.src.name}'")
                self.finished.emit(True, self.dst, "ok")
            else:
                total = self.stat.st_size
                logging.info(f"[FileMoveWorker] Cross-drive detected: performing chunked copy for '{self.src.name}' (Size: {total} bytes)")
                copied = 0
                last_logged_pct = -10
                progress_state = {"last_pct": -1, "last_emit": 0.0}

                try:
                    with open(self.src, 'rb') as fsrc, open(self.dst, 'wb') as fdst:
                        while True:
                            chunk = fsrc.read(1024 * 1024) # 1MB chunks
                            if not chunk:
                                break
                            fdst.write(chunk)
                            copied += len(chunk)

                            if total > 0:
                                pct = int(copied * 100 / total)
                                self._emit_progress(pct, progress_state)
                                # Log progress in 10% steps to avoid spamming while giving robust visibility
                                if pct - last_logged_pct >= 10:
                                    logging.info(f"[FileMoveWorker] '{self.src.name}' progress: {pct}% ({copied}/{total} bytes)")
                                    last_logged_pct = pct

                        fdst.flush()
                        os.fsync(fdst.fileno())  # Ensure data is written to disk

                    try:
                        self._restore_timestamps()
                    except Exception as ts_err:
                        logging.exception(f"[FileMoveWorker] Timestamp restore failed for '{self.dst}': {ts_err}")
                        self.finished.emit(False, self.dst, "TIMESTAMP_RESTORE_FAILED")
                        return

                    logging.info(f"[FileMoveWorker] Copy finished. Liberating source file: '{self.src.name}'")
                    if not safe_unlink(self.src):
                        raise PermissionError(f"Could not delete source after copy: {self.src}")

                    logging.info(f"[FileMoveWorker] Cross-drive move completed successfully for '{self.dst.name}'")
                    self.finished.emit(True, self.dst, "ok")
                except Exception as copy_err:
                    logging.error(f"[FileMoveWorker] Exception during cross-drive copy of '{self.src.name}': {copy_err}")
                    if self.dst.exists():
                        try:
                            logging.info(f"[FileMoveWorker] Cleaning up partially written destination: '{self.dst}'")
                            self.dst.unlink(missing_ok=True)
                        except Exception as clean_err:
                            logging.warning(f"[FileMoveWorker] Cleanup failed: {clean_err}")
                    raise copy_err

        except PermissionError as perm_err:
            logging.error(f"[FileMoveWorker] PermissionError for '{self.src.name}': {perm_err}")
            # Clean up partially written file if cross-drive failed mid-way
            if self.dst.exists():
                try:
                    logging.info(f"[FileMoveWorker] Cleaning up destination: '{self.dst}'")
                    self.dst.unlink(missing_ok=True)
                except Exception:
                    pass
            self.finished.emit(False, self.dst, "FILE_LOCKED")
        except Exception as e:
            logging.error(f"[FileMoveWorker] Error moving '{self.src.name}': {e}")
            # Clean up partially written file if cross-drive failed mid-way
            if self.dst.exists():
                try:
                    logging.info(f"[FileMoveWorker] Cleaning up destination: '{self.dst}'")
                    self.dst.unlink(missing_ok=True)
                except Exception:
                    pass
            self.finished.emit(False, self.dst, str(e))
