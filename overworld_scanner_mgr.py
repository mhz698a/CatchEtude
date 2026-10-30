"""Load Overworld subfolder names without calculating per-folder file statistics."""

import logging
from pathlib import Path

from PyQt6 import QtCore

from overworld_cache_mgr import OverworldCacheManager


logger = logging.getLogger("overworld.scanner")


class OverworldScanner(QtCore.QThread):
    """Emit one row per subfolder; Overworld buttons intentionally have one line."""

    result_ready = QtCore.pyqtSignal(str, str, str)

    def __init__(self, base_path: Path, cache: OverworldCacheManager | None = None):
        super().__init__()
        self.base_path = Path(base_path)
        # Keep the argument for compatibility with existing call sites.
        self.cache = cache
        self._abort = False

    def abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        if not self.base_path.is_dir():
            return

        try:
            subfolders = sorted(
                (path for path in self.base_path.iterdir() if path.is_dir()),
                key=lambda path: path.name.casefold(),
            )
            for subfolder in subfolders:
                if self._abort:
                    break
                self.result_ready.emit(subfolder.name, "", "")
        except OSError:
            logger.exception("Could not enumerate Overworld directory %s", self.base_path)
