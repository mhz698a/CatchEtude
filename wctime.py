"""
Windows Creation Time Utility - Low-level module to modify file creation timestamps.
Utilidad de Tiempo de Creación en Windows: módulo de bajo nivel para modificar las marcas de tiempo de creación de archivos.
"""

import ctypes
import time

class FILETIME(ctypes.Structure):
    """Win32 FILETIME structure."""
    _fields_ = [
        ("dwLowDateTime", ctypes.c_uint32),
        ("dwHighDateTime", ctypes.c_uint32),
    ]

kernel32 = ctypes.windll.kernel32

kernel32.CreateFileW.argtypes = (
    ctypes.c_wchar_p,   # lpFileName
    ctypes.c_uint32,    # dwDesiredAccess
    ctypes.c_uint32,    # dwShareMode
    ctypes.c_void_p,    # lpSecurityAttributes
    ctypes.c_uint32,    # dwCreationDisposition
    ctypes.c_uint32,    # dwFlagsAndAttributes
    ctypes.c_void_p,    # hTemplateFile
)
kernel32.CreateFileW.restype = ctypes.c_void_p

kernel32.SetFileTime.argtypes = (
    ctypes.c_void_p,
    ctypes.POINTER(FILETIME),
    ctypes.c_void_p,
    ctypes.c_void_p,
)
kernel32.SetFileTime.restype = ctypes.c_int

kernel32.CloseHandle.argtypes = (
    ctypes.c_void_p,
)
kernel32.CloseHandle.restype = ctypes.c_int

kernel32.GetLastError.restype = ctypes.c_uint32

# Win32 Constants
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
ERROR_SHARING_VIOLATION = 32
ERROR_LOCK_VIOLATION = 33
FILE_WRITE_ATTRIBUTES = 0x100
OPEN_EXISTING = 3
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
FILE_SHARE_DELETE = 4


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

    if handle == INVALID_HANDLE_VALUE:
        error = kernel32.GetLastError()
        raise OSError(error, "CreateFileW failed")

    try:
        result = kernel32.SetFileTime(
            handle,
            ctypes.byref(ft),
            None,
            None,
        )

        if not result:
            error = kernel32.GetLastError()
            raise OSError(error, "SetFileTime failed")
    finally:
        kernel32.CloseHandle(handle)

def setctime_blocking(
    path: str,
    ts: float,
    retry: float = 0.9,
    max_attempts: int | None = 60,
):
    attempts = 0

    while True:
        try:
            _set_creation_time(path, ts)
            return

        except OSError as e:
            if e.errno not in (
                ERROR_SHARING_VIOLATION,
                ERROR_LOCK_VIOLATION,
            ):
                raise

            attempts += 1

            if (
                max_attempts is not None
                and attempts >= max_attempts
            ):
                raise TimeoutError(
                    f"Could not set creation time for '{path}' after {attempts} attempts."
                ) from e

            time.sleep(retry)