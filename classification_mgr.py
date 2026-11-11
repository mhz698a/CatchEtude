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
    """Backward-compatible wrapper around the JSON-driven base-path resolver."""
    from classification_registry import ClassificationRegistry
    from decision_dispatcher import DecisionDispatcher

    registry = ClassificationRegistry()
    decision = registry.get_decision(movement_type)
    if decision is None:
        logging.warning("No classification definition for ID %s", movement_type)
        return config.BASE_INTERNAL / str(year)
    return DecisionDispatcher(registry=registry).resolve_base_path(decision, year) or (
        config.BASE_INTERNAL / str(year)
    )

def get_base_path_for_docs(movement_type: int) -> Path:
    """Backward-compatible wrapper; the destination is defined in classifications.json."""
    from classification_registry import ClassificationRegistry
    from decision_dispatcher import DecisionDispatcher

    registry = ClassificationRegistry()
    decision = registry.get_decision(movement_type)
    if decision is None:
        raise ValueError(f"No classification definition for ID {movement_type}")
    base = DecisionDispatcher(registry=registry).resolve_base_path(decision, None)
    if base is None:
        raise ValueError(f"Classification {movement_type} does not define a folder path")
    return base
