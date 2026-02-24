import hashlib, ctypes, shutil, logging, os
from ctypes import wintypes
from pathlib import Path
from config import EXCLUDE_EXT, BASE_INTERNAL, DOWNLOADS, DWMWA_FORCE_ICONIC_REPRESENTATION, DWMWA_HAS_ICONIC_BITMAP, DWMWA_DISALLOW_PEEK
from wctime import setctime_blocking
from typing import Optional


# Cargar DWMAPI y Shell32
dwmapi = ctypes.WinDLL('dwmapi')
shell32 = ctypes.WinDLL('shell32')

# SHFileOperation constants
FO_MOVE = 0x0001
FO_DELETE = 0x0003
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004
FOF_NOERRORUI = 0x0400

class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_ushort),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]

shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
shell32.SHFileOperationW.restype = ctypes.c_int


# -----------------------
# Utilities
# -----------------------

def sha256_file(p: Path, block_size=65536) -> Optional[str]:
    try:
        h = hashlib.sha256()
        with p.open('rb') as f:
            for chunk in iter(lambda: f.read(block_size), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None

def is_temporary(p: Path) -> bool:
    return p.suffix.lower() in EXCLUDE_EXT
    
def is_file_locked(p: Path) -> bool:
    try: 
        with open(p, 'rb'): 
            return False
    except OSError:
        return True    

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

def move_file_shfileop(src: Path, dst: Path, show_progress: bool = True) -> bool:
    """Moves a file using SHFileOperationW (Windows native move)."""
    try:
        # Paths must be double-null terminated
        from_path = str(src.absolute()).replace('/', '\\') + '\0\0'
        to_path = str(dst.absolute()).replace('/', '\\') + '\0\0'

        flags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION
        if not show_progress:
            flags |= FOF_SILENT | FOF_NOERRORUI

        fileop = SHFILEOPSTRUCTW()
        fileop.hwnd = 0
        fileop.wFunc = FO_MOVE
        fileop.pFrom = from_path
        fileop.pTo = to_path
        fileop.fFlags = flags
        
        result = shell32.SHFileOperationW(ctypes.byref(fileop))
        return result == 0 and not fileop.fAnyOperationsAborted
    except Exception:
        logging.exception(f"SHFileOperation move failed from {src} to {dst}")
        return False

def delete_to_recycle_bin(path: Path) -> bool:
    """Deletes a file to the Windows Recycle Bin."""
    try:
        if not path.exists():
            return False
            
        # Path must be double-null terminated
        from_path = str(path.absolute()).replace('/', '\\') + '\0\0'

        fileop = SHFILEOPSTRUCTW()
        fileop.hwnd = 0
        fileop.wFunc = FO_DELETE
        fileop.pFrom = from_path
        fileop.pTo = None
        fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION
        
        result = shell32.SHFileOperationW(ctypes.byref(fileop))
        return result == 0 and not fileop.fAnyOperationsAborted
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
    return BASE_INTERNAL.exists() and BASE_INTERNAL.is_dir()

def configure_dwm_thumbnail_behavior(hwnd):
    # Forzar que Windows use representación icónica
    dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_FORCE_ICONIC_REPRESENTATION,
                                 ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int))
    # Indicar que no tiene bitmap
    dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_HAS_ICONIC_BITMAP,
                                 ctypes.byref(ctypes.c_int(0)), ctypes.sizeof(ctypes.c_int(1)))
    # Deshabilitar peek
    dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_DISALLOW_PEEK,
                                 ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int(1)))


def flatten_downloads_root():
    """
    Aplana subcarpetas en Downloads de forma segura.
    NO interrumpe descargas.
    """
    for sub in DOWNLOADS.iterdir():
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

            dest = resolve_duplicate(DOWNLOADS / f.name)

            try:
                stat = f.stat()
                ctime = stat.st_ctime

                shutil.copy2(f, dest)

                if sha256_file(f) == sha256_file(dest):
                    setctime_blocking(str(dest), ctime)
                    f.unlink(missing_ok=True)
                    logging.info(f"Flattened: {f} -> {dest}")
                else:
                    dest.unlink(missing_ok=True)
                    logging.error(f"Hash mismatch flattening {f}")

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
