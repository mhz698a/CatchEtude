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

        # mover archivos uno por uno
        for f in list(sub.rglob('*')):
            if not f.is_file():
                continue

            dest = resolve_duplicate(config.DOWNLOADS / f.name)

            try:
                stat = f.stat()
                ctime = stat.st_ctime

                shutil.copy2(f, dest)

                setctime_blocking(str(dest), ctime)
                f.unlink(missing_ok=True)
                logging.info(f"Flattened: {f} -> {dest}")

            except Exception:
                logging.exception(f"Error flattening file {f}")
                continue

        # eliminar carpeta si quedó vacía
        try:
            if not any(sub.iterdir()):
                sub.rmdir()
                logging.info(f"Removed empty folder: {sub}")
        except Exception:
            logging.warning(f"Could not remove folder: {sub}")
