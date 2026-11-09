import logging
import shutil
from PyQt6 import QtCore
from pathlib import Path


from utils import (
    delete_to_recycle_bin,
    resolve_duplicate,
)

class _DuplicateDeleteSignals(QtCore.QObject):
    finished = QtCore.pyqtSignal(int, str, bool)


class _DuplicateDeleteWorker(QtCore.QRunnable):
    def __init__(self, operation_id: int, path: Path):
        super().__init__()
        self.operation_id = operation_id
        self.path = Path(path)
        self.signals = _DuplicateDeleteSignals()

    @QtCore.pyqtSlot()
    def run(self):
        try:
            success = delete_to_recycle_bin(self.path)
        except Exception:
            logging.exception("Failed to delete duplicate destination file: %s", self.path)
            success = False

        self.signals.finished.emit(self.operation_id, str(self.path), success)


class _QueueFileCopySignals(QtCore.QObject):
    finished = QtCore.pyqtSignal(int, object, object)


class _QueueFileCopyWorker(QtCore.QRunnable):
    """Copies queued files into a subfolder without blocking the UI thread."""

    def __init__(
        self,
        operation_id: int,
        target_folder: Path,
        sources: list[Path],
        destinations: dict[Path, Path] | None = None,
    ):
        super().__init__()
        self.operation_id = operation_id
        self.target_folder = Path(target_folder)
        self.sources = [Path(source) for source in sources]
        self.destinations = {
            Path(source): Path(destination)
            for source, destination in (destinations or {}).items()
        }
        self.signals = _QueueFileCopySignals()

    @QtCore.pyqtSlot()
    def run(self):
        copied = []
        failed = []

        for source in self.sources:
            try:
                if not source.is_file():
                    raise FileNotFoundError(f"El archivo ya no existe: {source}")
                if not self.target_folder.is_dir():
                    raise FileNotFoundError(
                        f"La carpeta de destino ya no existe: {self.target_folder}"
                    )

                destination = self.destinations.get(source)
                if destination is None:
                    destination = resolve_duplicate(self.target_folder / source.name)
                shutil.copy2(source, destination)
                copied.append(str(destination))
            except Exception as exc:
                logging.exception("Could not copy queued file %s", source)
                failed.append((str(source), str(exc)))

        self.signals.finished.emit(self.operation_id, copied, failed)
