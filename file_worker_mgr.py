"""
File Worker module - Handles background file operations.
Módulo File Worker: gestiona las operaciones de archivos en segundo plano.
"""

import os
import shutil
import logging
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

    def _restore_timestamps(self):
        """Restores source timestamps on the destination as part of the move operation."""
        try:
            os.utime(
                self.dst,
                (self.stat.st_atime, self.stat.st_mtime)
            )
            setctime_blocking(str(self.dst), getattr(self.stat, "st_birthtime", self.stat.st_ctime))
        except Exception as e:
            logging.warning(f"Could not restore timestamps on moved file: {e}")

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

                self._restore_timestamps()
                self.progress.emit(100)
                logging.info(f"[FileMoveWorker] Same-drive move completed successfully for '{self.src.name}'")
                self.finished.emit(True, self.dst, "ok")
            else:
                total = self.stat.st_size
                logging.info(f"[FileMoveWorker] Cross-drive detected: performing chunked copy for '{self.src.name}' (Size: {total} bytes)")
                copied = 0
                last_logged_pct = -10

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
                                self.progress.emit(pct)
                                # Log progress in 10% steps to avoid spamming while giving robust visibility
                                if pct - last_logged_pct >= 10:
                                    logging.info(f"[FileMoveWorker] '{self.src.name}' progress: {pct}% ({copied}/{total} bytes)")
                                    last_logged_pct = pct

                        fdst.flush()
                        os.fsync(fdst.fileno())  # Ensure data is written to disk

                    self._restore_timestamps()

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
