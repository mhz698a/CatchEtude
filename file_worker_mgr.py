"""
File Worker module - Handles background file operations.
Módulo File Worker: gestiona las operaciones de archivos en segundo plano.
"""

import os
from pathlib import Path
from PyQt6.QtCore import QObject, pyqtSignal


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
                
            total = self.stat.st_size
            copied = 0

            # Ensure destination directory exists
            self.dst.parent.mkdir(parents=True, exist_ok=True)

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
            os.utime(
                self.dst,
                (self.stat.st_atime, self.stat.st_mtime)
            )

            self.finished.emit(True, self.dst, "ok")

        except Exception as e:
            self.finished.emit(False, self.dst, str(e))
