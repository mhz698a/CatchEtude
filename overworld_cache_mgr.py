# overworld_cache_mgr.py
import json
import logging
import config

logger = logging.getLogger("overworld.cache")

class OverworldCacheManager:
    def __init__(self, year: int):
        self.year = year
        self.cache_path = config.CACHE_DIR / f"overworld_{year}.json"
        self.data = self._load()
        self._dirty = False

    def _load(self) -> dict:
        if self.cache_path.exists():
            try:
                with self.cache_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                logger.exception(f"Failed to load overworld cache for {self.year}")
        return {}

    def save(self):
        if not self._dirty:
            return
        try:
            tmp_path = self.cache_path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            tmp_path.replace(self.cache_path)
            self._dirty = False
        except Exception:
            logger.exception(f"Failed to save overworld cache for {self.year}")

    def get_folder_data(self, path: str) -> dict | None:
        return self.data.get(path)

    def update_folder(self, path: str, mtime_ns: int, file_count: int, total_size: int, size_mb_str: str):
        self.data[path] = {
            "mtime_ns": mtime_ns,
            "file_count": file_count,
            "total_size": total_size,
            "size_mb_str": size_mb_str,
        }
        self._dirty = True