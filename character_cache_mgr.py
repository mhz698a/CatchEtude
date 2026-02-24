"""
Character Cache Manager - Atomic JSON persistence for character metadata.
Gestor de Caché de Personajes: persistencia JSON atómica para metadatos de personajes.
"""

import json
import logging
from pathlib import Path
from config import CACHE_DIR

class CharacterCacheManager:
    """
    Manages a persistent cache of character folder metadata for a specific year.
    Gestiona una caché persistente de metadatos de carpetas de personajes para un año específico.
    """
    def __init__(self, year: int):
        self.year = year
        self.cache_path = CACHE_DIR / f"characters_{year}.json"
        self.data = self._load()
        self._dirty = False

    def _load(self) -> dict:
        if self.cache_path.exists():
            try:
                with self.cache_path.open('r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                logging.exception(f"Failed to load character cache for {self.year}")
        return {}

    def save(self):
        if not self._dirty:
            return
            
        try:
            tmp_path = self.cache_path.with_suffix(".tmp")
            with tmp_path.open('w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2)
            tmp_path.replace(self.cache_path)
            self._dirty = False
        except Exception:
            logging.exception(f"Failed to save character cache for {self.year}")

    def get_folder_data(self, path: str) -> dict:
        return self.data.get(path)

    def update_folder(self, path: str, mtime_ns: int, entry_count: int, 
                      file_count: int, total_size: int, metadata: dict,
                      age_str: str, size_mb_str: str):
        self.data[path] = {
            "mtime_ns": mtime_ns,
            "entry_count": entry_count,
            "file_count": file_count,
            "total_size": total_size,
            "metadata": metadata,
            "age_str": age_str,
            "size_mb_str": size_mb_str
        }
        self._dirty = True

    def remove_stale_entries(self, active_paths: set[str]):
        """Removes entries from the cache that no longer exist on disk."""
        to_remove = [p for p in self.data if p not in active_paths]
        for p in to_remove:
            del self.data[p]
            self._dirty = True
