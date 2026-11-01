# WinAPI helpers for file times and exclusive-open check
import ctypes, stat, time, os

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

CreateFileW = kernel32.CreateFileW
CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p]
CreateFileW.restype = ctypes.c_void_p

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [ctypes.c_void_p]
CloseHandle.restype = ctypes.c_int

SetFileTime = kernel32.SetFileTime
SetFileTime.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64)]
SetFileTime.restype = ctypes.c_int

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_NONE = 0x0
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
FILE_SHARE_DELETE = 0x4
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_WRITE_ATTRIBUTES = 0x100

def epoch_to_filetime_int(ts: float) -> int:
    return int(ts * 10000000) + 116444736000000000

def set_creation_and_modification_windows(path: str, creation_ts: float, modification_ts: float):
    """
    Set creation and modification times on Windows (best-effort). Raises OSError on fatal failure.
    """
    c_ft = epoch_to_filetime_int(creation_ts)
    m_ft = epoch_to_filetime_int(modification_ts)
    c_ft_ctypes = ctypes.c_uint64(c_ft)
    m_ft_ctypes = ctypes.c_uint64(m_ft)

    h = CreateFileW(path, FILE_WRITE_ATTRIBUTES, FILE_SHARE_NONE, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
    if h == INVALID_HANDLE_VALUE or h is None:
        h = CreateFileW(path, GENERIC_WRITE, FILE_SHARE_NONE, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
        if h == INVALID_HANDLE_VALUE or h is None:
            raise OSError(f"Unable to open file to set times: {path} (error {ctypes.get_last_error()})")

    res = SetFileTime(h, ctypes.byref(c_ft_ctypes), None, ctypes.byref(m_ft_ctypes))
    CloseHandle(h)
    if res == 0:
        raise OSError(f"SetFileTime failed for: {path} (error {ctypes.get_last_error()})")

def wait_until_file_unlocked(path: str, poll_interval: float = 0.4):
    """
    Poll until the file can be opened for reading exclusively (no sharing).
    """
    while True:
        h = CreateFileW(path, GENERIC_READ, FILE_SHARE_NONE, None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None)
        if h != INVALID_HANDLE_VALUE and h is not None:
            CloseHandle(h)
            return
        time.sleep(poll_interval)

def es_solo_lectura_windows(ruta):
    return bool(os.stat(ruta).st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)

def can_write_file(path: str) -> bool:
    """
    Heuristic to determine if this process likely has permission to modify the file contents:
    1) os.access(path, os.W_OK)
    2) attempt to open in 'r+b' (read+write binary). If both pass, we assume we can write metadata.
    """
    try:
        if not os.path.exists(path):
            return False
        # quick ACL check
        if not os.access(path, os.W_OK):
            return False
    except Exception:
        # if os.access is unreliable, fall back to trying to open
        pass

    try:
        # open in r+b to test write ability without truncating
        with open(path, 'r+b'):
            pass
        return True
    except PermissionError:
        return False
    except Exception:
        # other exceptions (locked, nonexistent, etc.) treated as inability to write
        return False
    
def is_file_in_use(path: str) -> bool:
    """
    Devuelve True si el archivo está en uso por otro proceso.
    No bloquea, no espera.
    """
    h = CreateFileW(
        path,
        GENERIC_READ,
        FILE_SHARE_NONE,
        None,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        None
    )
    if h == INVALID_HANDLE_VALUE or h is None:
        return True
    CloseHandle(h)
    return False