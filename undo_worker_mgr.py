"""Background worker for restoring files from move history."""

import logging
import os
import shutil
import time
from pathlib import Path

from PyQt6 import QtCore
from utils import is_same_drive, reserve_unique_destination
from wctime import setctime_blocking


def _notify_progress(callback, value: int, detail: str) -> None:
    if callback is None:
        return
    try:
        callback(max(0, min(100, int(value))), detail)
    except Exception:
        logging.exception("Undo progress callback failed")


def _restore_metadata(path: Path, metadata: dict) -> None:
    atime = metadata.get("atime")
    mtime = metadata.get("mtime")
    if atime is not None and mtime is not None:
        try:
            os.utime(path, (atime, mtime))
        except Exception:
            logging.exception("Could not restore access/modification timestamps: %s", path)

    ctime = metadata.get("ctime")
    if ctime is not None:
        try:
            setctime_blocking(str(path), ctime)
        except Exception:
            logging.exception("Could not restore creation timestamp: %s", path)


def perform_undo_move(entry: dict, progress_callback=None) -> tuple[bool, Path | None, str]:
    """Restore one history entry without blocking the caller's thread.

    Same-volume restores use a fast rename. Cross-volume restores copy in chunks,
    report byte progress, and delete the moved copy only after the destination is
    complete. Existing files are never overwritten.
    """
    source = Path(entry.get("dst", ""))
    original = Path(entry.get("src", ""))
    metadata = entry.get("meta") or {}

    if not source.is_file():
        return False, None, f"No se puede deshacer: falta el archivo {source.name}."

    try:
        original.parent.mkdir(parents=True, exist_ok=True)

        if is_same_drive(source, original):
            while True:
                target = reserve_unique_destination(original)
                try:
                    shutil.move(str(source), str(target))
                    break
                except FileExistsError:
                    continue

            _restore_metadata(target, metadata)
            _notify_progress(progress_callback, 100, "Movimiento completado.")
            logging.info("Physical Undo successful: %s -> %s", source, target)
            return True, target, ""

        total = source.stat().st_size
        source_stream = source.open("rb")
        target = None
        descriptor = None
        try:
            while True:
                candidate = reserve_unique_destination(original)
                try:
                    descriptor = os.open(
                        str(candidate),
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                        0o666,
                    )
                    target = candidate
                    break
                except FileExistsError:
                    continue

            copied = 0
            last_percent = -1
            last_emit = 0.0
            with os.fdopen(descriptor, "wb") as destination_stream:
                descriptor = None
                while True:
                    chunk = source_stream.read(1024 * 1024)
                    if not chunk:
                        break
                    destination_stream.write(chunk)
                    copied += len(chunk)

                    percent = int(copied * 100 / total) if total else 100
                    now = time.monotonic()
                    if percent >= last_percent + 1 or now - last_emit >= 0.1:
                        _notify_progress(
                            progress_callback,
                            percent,
                            f"{copied:,} de {total:,} bytes",
                        )
                        last_percent = percent
                        last_emit = now

                destination_stream.flush()
                os.fsync(destination_stream.fileno())

            try:
                shutil.copystat(source, target)
            except Exception:
                logging.exception("Could not copy file metadata during undo: %s", target)

            _restore_metadata(target, metadata)
            source.unlink()
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            if target is not None:
                target.unlink(missing_ok=True)
            raise
        finally:
            source_stream.close()

        _notify_progress(progress_callback, 100, "Restauración completada.")
        logging.info("Physical Undo successful: %s -> %s", source, target)
        return True, target, ""
    except Exception as exc:
        logging.exception("Physical Undo failed for %s", source)
        return False, None, str(exc)


class UndoMoveSignals(QtCore.QObject):
    progress = QtCore.pyqtSignal(int, str)
    finished = QtCore.pyqtSignal(bool, str, str)


class UndoMoveWorker(QtCore.QRunnable):
    """QRunnable wrapper that restores a history entry on a thread-pool worker."""

    def __init__(self, entry: dict):
        super().__init__()
        self.entry = dict(entry)
        self.signals = UndoMoveSignals()

    @QtCore.pyqtSlot()
    def run(self):
        success, target, error = perform_undo_move(
            self.entry,
            progress_callback=self.signals.progress.emit,
        )
        self.signals.finished.emit(
            success,
            str(target) if target else "",
            error,
        )
