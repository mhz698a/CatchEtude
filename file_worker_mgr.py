"""
File Worker module - Handles background file operations.
Módulo File Worker: gestiona las operaciones de archivos en segundo plano.
"""

import os
import shutil
import logging
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal
from utils import is_same_drive


class FileMoveWorker(QObject):
    """
    Worker that performs a file copy with progress reporting.
    Trabajador que realiza una copia de archivo con reporte de progreso.
    """
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, Path, str)

    def __init__(self, src: Path, dst: Path):
        super().__init__()
        self.src = src
        self.dst = dst
        try:
            self.stat = self.src.stat()
        except Exception:
            self.stat = None

    def run(self):
        """Executes the copy operation."""
        try:
            if not self.stat:
                self.stat = self.src.stat()

            # Ensure destination directory exists
            self.dst.parent.mkdir(parents=True, exist_ok=True)

            if is_same_drive(self.src, self.dst):
                # Same-drive move is atomic, fast and extremely safe.
                shutil.move(str(self.src), str(self.dst))

                # Restore timestamps - wrap in try-except so a failing utime doesn't destroy the file
                try:
                    os.utime(
                        self.dst,
                        (self.stat.st_atime, self.stat.st_mtime)
                    )
                except Exception as e:
                    logging.warning(f"Could not restore timestamps on same-drive move: {e}")

                self.progress.emit(100)
                self.finished.emit(True, self.dst, "ok")
            else:
                total = self.stat.st_size
                copied = 0

                try:
                    with open(self.src, 'rb') as fsrc, open(self.dst, 'wb') as fdst:
                        while True:
                            chunk = fsrc.read(1024 * 1024) # 1MB chunks
                            if not chunk:
                                break
                            fdst.write(chunk)
                            copied += len(chunk)

                            if total > 0:
                                self.progress.emit(int(copied * 100 / total))

                        fdst.flush()
                        os.fsync(fdst.fileno())  # Ensure data is written to disk

                    # Restore timestamps
                    try:
                        os.utime(
                            self.dst,
                            (self.stat.st_atime, self.stat.st_mtime)
                        )
                    except Exception as e:
                        logging.warning(f"Could not restore timestamps on cross-drive copy: {e}")

                    self.finished.emit(True, self.dst, "ok")
                except Exception as copy_err:
                    if self.dst.exists():
                        try:
                            self.dst.unlink(missing_ok=True)
                        except Exception:
                            pass
                    raise copy_err

        except PermissionError:
            # Clean up partially written file if cross-drive failed mid-way
            if self.dst.exists():
                try:
                    self.dst.unlink(missing_ok=True)
                except Exception:
                    pass
            self.finished.emit(False, self.dst, "FILE_LOCKED")
        except Exception as e:
            # Clean up partially written file if cross-drive failed mid-way
            if self.dst.exists():
                try:
                    self.dst.unlink(missing_ok=True)
                except Exception:
                    pass
            self.finished.emit(False, self.dst, str(e))
