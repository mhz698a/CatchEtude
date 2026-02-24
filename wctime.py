"""
Windows Creation Time Utility - Low-level module to modify file creation timestamps.
Utilidad de Tiempo de Creación en Windows: módulo de bajo nivel para modificar las marcas de tiempo de creación de archivos.
"""

import ctypes
import time

kernel32 = ctypes.windll.kernel32

# Win32 Constants
FILE_WRITE_ATTRIBUTES = 0x100
OPEN_EXISTING = 3
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
FILE_SHARE_DELETE = 4

class FILETIME(ctypes.Structure):
    """Win32 FILETIME structure."""
    _fields_ = [
        ("dwLowDateTime", ctypes.c_uint32),
        ("dwHighDateTime", ctypes.c_uint32),
    ]

def ts_to_filetime(ts: float) -> FILETIME:
    """Converts a Unix timestamp to Win32 FILETIME."""
    timestamp = int((ts + 11644473600) * 10_000_000)
    return FILETIME(timestamp & 0xFFFFFFFF, timestamp >> 32)

def _set_creation_time(path: str, ts: float):
    """Sets the creation time of a file using Win32 API."""
    ft = ts_to_filetime(ts)

    handle = kernel32.CreateFileW(
        path,
        FILE_WRITE_ATTRIBUTES,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None,
        OPEN_EXISTING,
        0,
        None
    )

    if handle == -1:
        raise OSError("Could not open file to set creation time (might be in use).")

    kernel32.SetFileTime(handle, ctypes.byref(ft), None, None)
    kernel32.CloseHandle(handle)

def setctime_blocking(path: str, ts: float, retry: float = 0.9):
    """
    Sets the creation time, blocking and retrying if the file is in use.
    Establece la fecha de creación, bloqueando y reintentando si el archivo está en uso.
    """
    while True:
        try:
            _set_creation_time(path, ts)
            return
        except OSError:
            time.sleep(retry)
