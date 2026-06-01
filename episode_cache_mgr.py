import json
import logging
from config import CACHE_DIR


class EpisodeCacheManager:
    def __init__(self, year: int):
        self.year = year
        self.cache_path = CACHE_DIR / f"episodes_{year}.json"
        self.data = self._load()
        self._dirty = False

    def _load(self) -> dict:
        if self.cache_path.exists():
            try:
                with self.cache_path.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                logging.exception(f"Failed to load episode cache for {self.year}")
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
            logging.exception(f"Failed to save episode cache for {self.year}")

    def get_folder_data(self, path: str) -> dict | None:
        return self.data.get(path)

    def update_folder(self, path: str, mtime_ns: int, last_alpha_file: str):
        self.data[path] = {
            "mtime_ns": mtime_ns,
            "last_alpha_file": last_alpha_file,
        }
        self._dirty = True