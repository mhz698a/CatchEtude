import os
import hashlib, ctypes, shutil, logging
import time
import win32file, win32con, pywintypes

from send2trash import send2trash
from pathlib import Path
import config
from wctime import setctime_blocking
from typing import Optional
from PyQt6 import QtCore

class GenericRunnable(QtCore.QRunnable):
    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            self.func(*self.args, **self.kwargs)
        except Exception as e:
            import logging
            logging.exception(f"Exception in run_in_threadpool: {e}")

def run_in_threadpool(func, *args, **kwargs):
    runnable = GenericRunnable(func, *args, **kwargs)
    QtCore.QThreadPool.globalInstance().start(runnable)


# Cargar DWMAPI
dwmapi = ctypes.WinDLL('dwmapi')


# -----------------------
# Utilities
# -----------------------

def is_temporary(p: Path) -> bool:
    return p.suffix.lower() in config.EXCLUDE_EXT

def is_file_locked(p: Path) -> bool:
    """Verifica si el archivo está bloqueado sin interferir con otros procesos."""
    try:
        # 'r+b' pide verificar lectura/escritura, lo que detecta descargas y conversiones activas
        with open(p, 'r+b'):
            return False
    except (OSError, PermissionError):
        return True


def safe_unlink(path: Path, retries=20, delay=0.25):
    for i in range(retries):
        try:
            path.unlink(missing_ok=True)
            return True
        except PermissionError:
            time.sleep(delay)

    return False

def resolve_duplicate(dest: Path) -> Path:
    if not dest.exists():
        return dest

    orig = dest.stem
    ext = dest.suffix
    parent = dest.parent
    i = 1
    while True:
        cand = parent / f"{orig}_{i}{ext}"
        if not cand.exists():
            return cand
        i += 1

def folder_is_safe_to_flatten(folder: Path) -> bool:
    """
    Una carpeta es segura si TODOS sus archivos:
    - no son temporales
    - no están bloqueados
    """
    for p in folder.rglob('*'):
        if not p.is_file():
            continue
        if is_temporary(p):
            return False
        if is_file_locked(p):
            return False
    return True

def sanitize_windows_filename(name: str) -> str:
    illegal = '<>:"/\\|?*'
    return ''.join('_' if c in illegal else c for c in name).strip()

def is_same_drive(p1: Path, p2: Path) -> bool:
    """Checks if two paths are on the same Windows drive."""
    try:
        # Resolve to absolute paths and normalize backslashes/casing for Windows
        abs1 = str(Path(p1).absolute()).lower()
        abs2 = str(Path(p2).absolute()).lower()
        return os.path.splitdrive(abs1)[0] == os.path.splitdrive(abs2)[0]
    except Exception:
        return False

def delete_to_recycle_bin(path: Path) -> bool:
    """Deletes a file to the Windows Recycle Bin."""
    try:
        if not path.exists():
            return False

        send2trash(str(path))
        return True
    except Exception:
        logging.exception(f"Failed to delete to recycle bin: {path}")
        return False

def update_folder_mtime(folder_path: Path):
    """Updates the modification time of a folder to the current time."""
    try:
        if folder_path.exists() and folder_path.is_dir():
            import time
            now = time.time()
            os.utime(folder_path, (now, now))
    except Exception:
        logging.exception(f"Failed to update mtime for folder: {folder_path}")

def is_internal_available() -> bool:
    return config.BASE_INTERNAL.exists() and config.BASE_INTERNAL.is_dir()

def configure_dwm_thumbnail_behavior(hwnd):
    # Forzar que Windows use representación icónica
    dwmapi.DwmSetWindowAttribute(hwnd, config.DWMWA_FORCE_ICONIC_REPRESENTATION,
                                 ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
    # Indicar que no tiene bitmap
    dwmapi.DwmSetWindowAttribute(hwnd, config.DWMWA_HAS_ICONIC_BITMAP,
                                 ctypes.byref(ctypes.c_int(0)), ctypes.sizeof(ctypes.c_int(1)))
    # Deshabilitar peek
    dwmapi.DwmSetWindowAttribute(hwnd, config.DWMWA_DISALLOW_PEEK,
                                 ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int(1)))


def flatten_single_folder(folder: Path, progress_callback=None) -> tuple[list[Path], bool]:
    """
    Flatten a folder into Downloads and report progress through an optional callback.

    The callback receives (completed, total, current_path, phase), where phase is
    "scan" while enumerating files and "move" while processing them.
    """
    if not folder.exists() or not folder.is_dir():
        return [], True

    moved_files = []
    flatten_failed = False

    def report(completed: int, total: int, current_path: str = "", phase: str = "move"):
        if progress_callback is None:
            return
        try:
            progress_callback(completed, total, current_path, phase)
        except Exception:
            logging.debug("Flatten progress callback failed", exc_info=True)

    report(0, 0, "", "scan")
    if not folder_is_safe_to_flatten(folder):
        flatten_failed = True

    try:
        entries = list(folder.rglob("*"))
    except Exception:
        logging.exception("Could not enumerate folder for flattening: %s", folder)
        return [], False

    files = []
    for entry in entries:
        try:
            if entry.is_file():
                files.append(entry)
        except OSError:
            flatten_failed = True

    total = len(files)
    report(0, total, "", "move")

    for index, file_path in enumerate(files, start=1):
        try:
            if is_temporary(file_path) or is_file_locked(file_path):
                flatten_failed = True
                continue

            destination = resolve_duplicate(config.DOWNLOADS / file_path.name)
            stat = file_path.stat()
            creation_time = stat.st_ctime

            shutil.copy2(file_path, destination)
            setctime_blocking(str(destination), creation_time)
            file_path.unlink(missing_ok=True)
            logging.info("Flattened: %s -> %s", file_path, destination)
            moved_files.append(destination)
        except Exception:
            logging.exception("Error flattening file %s", file_path)
            flatten_failed = True
        finally:
            report(index, total, str(file_path), "move")

    folder_removed = False
    try:
        for sub in sorted(folder.rglob("*"), reverse=True):
            if sub.is_dir() and not any(sub.iterdir()):
                sub.rmdir()
        if folder.exists() and not any(folder.iterdir()):
            folder.rmdir()
            folder_removed = True
            logging.info("Removed empty folder after manual flatten: %s", folder)
    except Exception:
        logging.warning("Could not remove folder structure: %s", folder, exc_info=True)
        flatten_failed = True

    success = folder_removed and not folder.exists() and not flatten_failed
    report(total, total, "", "finished")
    return moved_files, success


def flatten_downloads_root():
    """
    Aplana subcarpetas en Downloads de forma segura.
    NO interrumpe descargas.
    """
    for sub in config.DOWNLOADS.iterdir():
        if not sub.is_dir():
            continue

        logging.debug(f"Evaluating folder for flatten: {sub}")

        if not folder_is_safe_to_flatten(sub):
            logging.debug(f"Folder not safe yet: {sub}")
            continue

        flatten_single_folder(sub)
