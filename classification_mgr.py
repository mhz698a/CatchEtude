"""
Classification logic and scanning for CatchEtude.
Lógica de clasificación y escaneo para CatchEtude.
"""

import os
import logging
from pathlib import Path
from PyQt6 import QtCore
import config
from episode_cache_mgr import EpisodeCacheManager

class SubfolderScanner(QtCore.QThread):
    """Background scanner to find the first file in subfolders."""
    result_ready = QtCore.pyqtSignal(str, str)

    def __init__(self, base_path: Path, cache: EpisodeCacheManager | None = None):
        super().__init__()
        self.base_path = base_path
        self.cache = cache
        self._abort = False

    def abort(self):
        self._abort = True

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
                
                last_file = "---"
                try:
                                        
                    try:
                        mtime_ns = os.stat(sub_path).st_mtime_ns
                    except Exception:
                        mtime_ns = None

                    cached = None
                    if self.cache is not None and mtime_ns is not None:
                        cached = self.cache.get_folder_data(sub_path)
                        if cached and cached.get("mtime_ns") == mtime_ns:
                            last_file = cached.get("last_alpha_file", "---")
                            self.result_ready.emit(Path(sub_path).name, last_file)
                            continue

                    files = []
                    try:
                        with os.scandir(sub_path) as it_f:
                            for entry in it_f:
                                if entry.is_file():
                                    n_low = entry.name.lower()
                                    if not (n_low.endswith(".ini") or n_low.endswith(".db")):
                                        files.append(entry.name)
                    except Exception:
                        pass

                    if files:
                        files.sort()
                        last_file = files[-1]

                    if self.cache is not None and mtime_ns is not None:
                        self.cache.update_folder(sub_path, mtime_ns, last_file)                    
                        
                except Exception:
                    pass
                
                self.result_ready.emit(Path(sub_path).name, last_file)
                
                if self.cache is not None:
                    self.cache.save()
                
        except Exception:
            logging.exception("Error in SubfolderScanner")

def get_base_path_for_type_year(movement_type: int, year: int) -> Path:
    """Calculates the base folder for subfolder listing."""
    year_dir = config.BASE_INTERNAL / str(year)
    if not (year_dir.exists() and year_dir.is_dir()):
        logging.warning(f"Year directory not found: {year_dir}")
        return year_dir
        
    prefix = f"{year - 2003:02d}"
    base = None
    
    try:
        for child in sorted(year_dir.iterdir()):
            if not child.is_dir():
                continue
            
            name = child.name.lower()
            if movement_type == 2: # Characters
                if (prefix in name and config.IMAGES_FOLDER in name) or (config.IMAGES_FOLDER in name):
                    base = child
                    break
            elif movement_type == 3: # Episodes
                if '___[' in name:
                    base = child
                    break
            elif movement_type == 4: # Music
                if (prefix in name and config.MUSIC_FOLDER in name) or (config.MUSIC_FOLDER in name):
                    base = child
                    break
            elif movement_type == 8: # Overworld
                if (prefix in name and config.OVERWORLD_FOLDER in name) or (config.OVERWORLD_FOLDER in name):
                    base = child
                    break
    except Exception:
        logging.exception(f"Error accessing year directory: {year_dir}")

    if base is None:
        if movement_type == 2:
            base = year_dir / f"{prefix}. {config.IMAGES_FOLDER}"
        elif movement_type == 4:
            base = year_dir / f"{prefix}. {config.MUSIC_FOLDER}"
        elif movement_type == 8:
            base = year_dir / f"{prefix}. {config.OVERWORLD_FOLDER}"
        else:
            base = year_dir
            
    return base

def get_base_path_for_docs(movement_type: int) -> Path:
    """Returns base path for OneDrive documents."""
    return config.ONEDRIVE_DOCS if movement_type == 5 else config.ONEDRIVE_DOCTOS_FAMILIA
