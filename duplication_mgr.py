import logging
from PyQt6 import QtCore
from pathlib import Path


from utils import (
    delete_to_recycle_bin
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
