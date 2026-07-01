# overworld_scanner_mgr.py
import logging
import os
from pathlib import Path
from PyQt6 import QtCore
from overworld_cache_mgr import OverworldCacheManager

logger = logging.getLogger("overworld.scanner")

class OverworldScanner(QtCore.QThread):
    result_ready = QtCore.pyqtSignal(str, str, str)

    def __init__(self, base_path: Path, cache: OverworldCacheManager | None = None):
        super().__init__()
        self.base_path = base_path
        self.cache = cache
        self._abort = False

    def abort(self):
        self._abort = True

    def _scan_folder_stats(self, folder_path: str) -> tuple[int, int]:
        file_count = 0
        total_size = 0

        for root, _, files in os.walk(folder_path):
            if self._abort:
                return file_count, total_size
            
            for fname in files:
                n_low = fname.lower()
                if n_low in ("desktop.ini", "thumbs.db"):
                    continue
                file_count += 1
                try:
                    total_size += os.path.getsize(os.path.join(root, fname))
                except OSError as e:
                    logger.exception(f"Error get size file: {e}")

        return file_count, total_size

    def _format_size_mb(self, total_size: int) -> str:
        return f"{total_size / (1024 * 1024):.1f} MB"

    def run(self):
        try:
            if not self.base_path.exists():
                return

            try:
                with os.scandir(str(self.base_path)) as it:
                    subs = sorted([e.path for e in it if e.is_dir()])
            except Exception:
                return

            for sub_path in subs:
                if self._abort:
                    break
                
                logger.debug(
                    "Scanning folder %s",
                    sub_path,
                )
                
                folder_name = Path(sub_path).name
                line2 = "0 archivos"
                line3 = "0.0 MB"

                try:
                    mtime_ns = os.stat(sub_path).st_mtime_ns
                except Exception:
                    mtime_ns = None

                if self.cache is not None and mtime_ns is not None:
                    cached = self.cache.get_folder_data(sub_path)
                    if cached and cached.get("mtime_ns") == mtime_ns:
                        logger.debug(
                            "Cache hit %s",
                            sub_path,
                        )
                        file_count = int(cached.get("file_count", 0))
                        total_size = int(cached.get("total_size", 0))
                        line2 = f"{file_count} archivos"
                        line3 = cached.get("size_mb_str", self._format_size_mb(total_size))
                        self.result_ready.emit(folder_name, line2, line3)
                        
                        if self.cache is not None and self.cache._dirty:
                            try:
                                self.cache.save()
                            except Exception:
                                logger.exception("Incremental cache save failed")
                                
                        continue

                file_count, total_size = self._scan_folder_stats(sub_path)
                logger.debug(
                    "Calculated files=%s bytes=%s",
                    file_count,
                    total_size,
                )
                line2 = f"{file_count} archivos"
                line3 = self._format_size_mb(total_size)

                if self.cache is not None and mtime_ns is not None:
                    self.cache.update_folder(sub_path, mtime_ns, file_count, total_size, line3)

                self.result_ready.emit(folder_name, line2, line3)

            if self.cache is not None:
                try:
                    self.cache.save()
                except Exception:
                    logger.exception("Error saving Overworld cache")

        except Exception:
            logger.exception("Error in OverworldScanner")