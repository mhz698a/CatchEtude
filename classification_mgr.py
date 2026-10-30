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

class EpisodeSubfolderListWorker(QtCore.QThread):
    """Enumerate episode subfolders off the UI thread before creating their buttons."""

    folders_ready = QtCore.pyqtSignal(list)

    def __init__(self, base_path: Path):
        super().__init__()
        self.base_path = Path(base_path)
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        folders = []
        try:
            with os.scandir(str(self.base_path)) as entries:
                for entry in entries:
                    if self._abort or self.isInterruptionRequested():
                        return
                    try:
                        if entry.is_dir():
                            folders.append(entry.path)
                    except OSError:
                        logging.debug(
                            "Could not inspect episode subfolder %s",
                            entry.path,
                            exc_info=True,
                        )

            folders.sort(key=lambda path: Path(path).name.casefold())
        except (FileNotFoundError, NotADirectoryError):
            logging.warning("Episode directory is no longer available: %s", self.base_path)
        except PermissionError:
            logging.warning("Permission denied listing episode folders: %s", self.base_path)
        except Exception:
            logging.exception("Could not enumerate episode folders in %s", self.base_path)

        if not self._abort and not self.isInterruptionRequested():
            self.folders_ready.emit(folders)


class SubfolderScanner(QtCore.QThread):
    """Background scanner to find the first file in subfolders."""
    result_ready = QtCore.pyqtSignal(str, str)

    def __init__(
        self,
        base_path: Path,
        cache: EpisodeCacheManager | None = None,
        subfolders: list[str] | None = None,
        cache_year: int | None = None,
    ):
        super().__init__()
        self.base_path = Path(base_path)
        self.cache = cache
        self.subfolders = subfolders
        self.cache_year = cache_year
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            if not self.base_path.exists():
                return
            
            if self.cache is None and self.cache_year is not None:
                # Loading the JSON cache can also involve disk I/O, so keep it off the UI thread.
                self.cache = EpisodeCacheManager(self.cache_year)

            if self.subfolders is None:
                try:
                    with os.scandir(str(self.base_path)) as entries:
                        subs = sorted(
                            [entry.path for entry in entries if entry.is_dir()],
                            key=lambda path: Path(path).name.casefold(),
                        )
                except FileNotFoundError:
                    logging.warning(f"Base path not found during subfolder scan: {self.base_path}")
                    return
                except PermissionError:
                    logging.warning(f"Permission denied scanning subfolders: {self.base_path}")
                    return
                except Exception as e:
                    logging.error(f"Error scanning base path {self.base_path}: {e}")
                    return
            else:
                subs = list(self.subfolders)

            for sub_path in subs:
                if self._abort:
                    break
                
                last_file = "---"
                try:
                                        
                    try:
                        mtime_ns = os.stat(sub_path).st_mtime_ns
                    except FileNotFoundError:
                        logging.debug(f"Subfolder disappeared during scan: {sub_path}")
                        mtime_ns = None
                    except PermissionError:
                        logging.warning(f"Permission denied accessing folder stats: {sub_path}")
                        mtime_ns = None
                    except Exception as e:
                        logging.warning(f"Error getting folder stats {sub_path}: {e}")
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
                                if self._abort or self.isInterruptionRequested():
                                    break
                                if entry.is_file():
                                    n_low = entry.name.lower()
                                    if not (n_low.endswith(".ini") or n_low.endswith(".db")):
                                        files.append(entry.name)
                    except FileNotFoundError:
                        logging.debug(f"Subfolder disappeared during file listing: {sub_path}")
                    except PermissionError:
                        logging.warning(f"Permission denied listing files in: {sub_path}")
                    except Exception as e:
                        logging.warning(f"Error listing files in {sub_path}: {e}")

                    if self._abort or self.isInterruptionRequested():
                        break

                    if files:
                        files.sort()
                        last_file = files[-1]

                    if self.cache is not None and mtime_ns is not None:
                        self.cache.update_folder(sub_path, mtime_ns, last_file)                    
                        
                except Exception as e:
                    logging.error(f"Unexpected error in subfolder scanner for {sub_path}: {e}")
                
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
