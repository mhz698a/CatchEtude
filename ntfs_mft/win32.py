"""Small, isolated ctypes wrapper for the Windows NTFS volume APIs.

The module deliberately avoids pywin32 so the MFT package remains reusable and
has no additional runtime dependency. Windows DLLs are loaded lazily, allowing
the record parser and scanner tests to run on non-Windows CI.
"""

from __future__ import annotations

import ctypes
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .errors import (
    ElevationRequiredError,
    MFTAccessError,
    MFTEnumerationError,
    UnsupportedFilesystemError,
    UnsupportedPlatformError,
    UnsupportedVolumeError,
)

GENERIC_READ = 0x80000000
FILE_READ_ATTRIBUTES = 0x0080
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20
FILE_STANDARD_INFO_CLASS = 1

FSCTL_ENUM_USN_DATA = 0x000900B3
ERROR_ACCESS_DENIED = 5
ERROR_NO_MORE_FILES = 18
ERROR_HANDLE_EOF = 38
ERROR_INVALID_FUNCTION = 1
ERROR_INVALID_PARAMETER = 87
DRIVE_REMOTE = 4
MAX_SIGNED_USN = 0x7FFFFFFFFFFFFFFF


@dataclass(frozen=True)
class VolumeInfo:
    filesystem: str
    volume_root: str
    device_path: str


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32),
                ("dwHighDateTime", ctypes.c_uint32)]


class _BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", ctypes.c_uint32),
        ("ftCreationTime", _FILETIME),
        ("ftLastAccessTime", _FILETIME),
        ("ftLastWriteTime", _FILETIME),
        ("dwVolumeSerialNumber", ctypes.c_uint32),
        ("nFileSizeHigh", ctypes.c_uint32),
        ("nFileSizeLow", ctypes.c_uint32),
        ("nNumberOfLinks", ctypes.c_uint32),
        ("nFileIndexHigh", ctypes.c_uint32),
        ("nFileIndexLow", ctypes.c_uint32),
    ]


class _TOKEN_ELEVATION(ctypes.Structure):
    _fields_ = [("TokenIsElevated", ctypes.c_uint32)]


class _FILE_ID_DESCRIPTOR_UNION(ctypes.Union):
    _fields_ = [
        ("FileId", ctypes.c_int64),
        ("ObjectId", ctypes.c_ubyte * 16),
        ("ExtendedFileId", ctypes.c_ubyte * 16),
    ]


class _FILE_ID_DESCRIPTOR(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("dwSize", ctypes.c_uint32),
        ("Type", ctypes.c_int),
        ("u", _FILE_ID_DESCRIPTOR_UNION),
    ]


class _FILE_STANDARD_INFO(ctypes.Structure):
    _fields_ = [
        ("AllocationSize", ctypes.c_int64),
        ("EndOfFile", ctypes.c_int64),
        ("NumberOfLinks", ctypes.c_uint32),
        ("DeletePending", ctypes.c_ubyte),
        ("Directory", ctypes.c_ubyte),
    ]


class WindowsVolumeApi:
    """Native NTFS functions used by the higher-level MFT scanner."""

    def __init__(self):
        if os.name != "nt":
            raise UnsupportedPlatformError("El acceso MFT solo está disponible en Windows.")
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        k32 = self.kernel32
        k32.GetVolumePathNameW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32
        ]
        k32.GetVolumePathNameW.restype = ctypes.c_int
        k32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        k32.GetDriveTypeW.restype = ctypes.c_uint32
        k32.GetVolumeInformationW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p, ctypes.c_uint32,
        ]
        k32.GetVolumeInformationW.restype = ctypes.c_int
        k32.CreateFileW.argtypes = [
            ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
        ]
        k32.CreateFileW.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.restype = ctypes.c_int
        k32.DeviceIoControl.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
            ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32),
            ctypes.c_void_p,
        ]
        k32.DeviceIoControl.restype = ctypes.c_int
        k32.GetFileInformationByHandle.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(_BY_HANDLE_FILE_INFORMATION)
        ]
        k32.GetFileInformationByHandle.restype = ctypes.c_int
        k32.GetFileInformationByHandleEx.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32
        ]
        k32.GetFileInformationByHandleEx.restype = ctypes.c_int
        k32.OpenFileById.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(_FILE_ID_DESCRIPTOR),
            ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
        ]
        k32.OpenFileById.restype = ctypes.c_void_p
        k32.GetCurrentProcess.argtypes = []
        k32.GetCurrentProcess.restype = ctypes.c_void_p

        self.advapi32.OpenProcessToken.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)
        ]
        self.advapi32.OpenProcessToken.restype = ctypes.c_int
        self.advapi32.GetTokenInformation.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        self.advapi32.GetTokenInformation.restype = ctypes.c_int

    @staticmethod
    def _raise_last_error(message: str, access_error: bool = False) -> None:
        error_code = ctypes.get_last_error()
        detail = ctypes.FormatError(error_code).strip() if error_code else "error desconocido"
        error = MFTAccessError if access_error or error_code == ERROR_ACCESS_DENIED else OSError
        raise error(f"{message} (Windows {error_code}: {detail})")

    @staticmethod
    def _extended_path(path: Path) -> str:
        value = str(Path(path).resolve())
        if value.startswith("\\\\?\\"):
            return value
        if value.startswith("\\\\"):
            return "\\\\?\\UNC\\" + value[2:]
        return "\\\\?\\" + value

    def get_volume_info(self, path: Path) -> VolumeInfo:
        target = str(Path(path).resolve())
        root_buffer = ctypes.create_unicode_buffer(32768)
        if not self.kernel32.GetVolumePathNameW(target, root_buffer, len(root_buffer)):
            self._raise_last_error(f"No se pudo resolver el volumen de {target}")

        volume_root = root_buffer.value
        if not volume_root.endswith("\\"):
            volume_root += "\\"

        filesystem_buffer = ctypes.create_unicode_buffer(64)
        serial = ctypes.c_uint32()
        max_component = ctypes.c_uint32()
        flags = ctypes.c_uint32()
        if not self.kernel32.GetVolumeInformationW(
            volume_root, None, 0, ctypes.byref(serial),
            ctypes.byref(max_component), ctypes.byref(flags),
            filesystem_buffer, len(filesystem_buffer),
        ):
            self._raise_last_error(f"No se pudo consultar el sistema de archivos de {volume_root}")

        # FSCTL_ENUM_USN_DATA is not supported by SMB shares. A mapped network
        # drive can still have a drive letter, so reject both UNC roots and
        # DRIVE_REMOTE before constructing a local \\\\.\\X: device path.
        if volume_root.startswith("\\\\") or (
            self.kernel32.GetDriveTypeW(volume_root) == DRIVE_REMOTE
        ):
            raise UnsupportedVolumeError(
                "El escaneo MFT no está disponible en unidades de red o recursos SMB."
            )

        # FSCTL_ENUM_USN_DATA expects a volume handle. A mounted folder that is
        # not the drive root is rejected rather than opening the wrong volume.
        drive, _ = os.path.splitdrive(volume_root)
        if not drive or volume_root.rstrip("\\").casefold() != (drive + "\\").rstrip("\\").casefold():
            raise UnsupportedVolumeError(
                "El escaneo MFT requiere una ruta montada directamente en una letra de unidad."
            )

        device_path = f"\\\\.\\{drive}"
        return VolumeInfo(filesystem_buffer.value, volume_root, device_path)

    def is_process_elevated(self) -> bool:
        token = ctypes.c_void_p()
        process = self.kernel32.GetCurrentProcess()
        if not self.advapi32.OpenProcessToken(
            process, TOKEN_QUERY, ctypes.byref(token)
        ):
            self._raise_last_error("No se pudo consultar el token del proceso")

        try:
            elevation = _TOKEN_ELEVATION()
            returned = ctypes.c_uint32()
            if not self.advapi32.GetTokenInformation(
                token, TOKEN_ELEVATION, ctypes.byref(elevation),
                ctypes.sizeof(elevation), ctypes.byref(returned),
            ):
                self._raise_last_error("No se pudo consultar el nivel de elevación")
            return bool(elevation.TokenIsElevated)
        finally:
            self.kernel32.CloseHandle(token)

    def require_elevated_process(self) -> None:
        if not self.is_process_elevated():
            raise ElevationRequiredError(
                "El escaneo MFT requiere que CatchEtude se ejecute como administrador."
            )

    def open_volume(self, volume: VolumeInfo):
        handle = self.kernel32.CreateFileW(
            volume.device_path,
            GENERIC_READ,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if handle in (None, ctypes.c_void_p(-1).value):
            self._raise_last_error(
                f"No se pudo abrir el volumen {volume.device_path}", access_error=True
            )
        return handle

    def close_handle(self, handle) -> None:
        if handle not in (None, ctypes.c_void_p(-1).value):
            self.kernel32.CloseHandle(handle)

    def get_file_reference(self, path: Path) -> int:
        handle = self.kernel32.CreateFileW(
            self._extended_path(path),
            FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if handle in (None, ctypes.c_void_p(-1).value):
            self._raise_last_error(f"No se pudo abrir la carpeta {path}")
        try:
            info = _BY_HANDLE_FILE_INFORMATION()
            if not self.kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
                self._raise_last_error(f"No se pudo obtener el identificador de {path}")
            return (int(info.nFileIndexHigh) << 32) | int(info.nFileIndexLow)
        finally:
            self.close_handle(handle)

    def open_file_hint(self, path: Path):
        """Open a file/directory handle usable as OpenFileById's volume hint."""
        handle = self.kernel32.CreateFileW(
            self._extended_path(path),
            FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS,
            None,
        )
        if handle in (None, ctypes.c_void_p(-1).value):
            self._raise_last_error(f"No se pudo abrir el identificador de volumen {path}")
        return handle

    def enumerate_usn_data(
        self, volume_handle, start_reference: int, buffer_size: int
    ) -> Optional[bytes]:
        # MFT_ENUM_DATA_V0: StartFileReferenceNumber, LowUsn, HighUsn.
        input_data = struct.pack("<Qqq", start_reference, 0, MAX_SIGNED_USN)
        input_buffer = ctypes.create_string_buffer(input_data)
        output_buffer = ctypes.create_string_buffer(buffer_size)
        bytes_returned = ctypes.c_uint32()

        ok = self.kernel32.DeviceIoControl(
            volume_handle,
            FSCTL_ENUM_USN_DATA,
            input_buffer,
            len(input_data),
            output_buffer,
            buffer_size,
            ctypes.byref(bytes_returned),
            None,
        )
        if not ok:
            error_code = ctypes.get_last_error()
            if error_code in (ERROR_HANDLE_EOF, ERROR_NO_MORE_FILES):
                return None
            if error_code == ERROR_ACCESS_DENIED:
                self._raise_last_error("Windows denegó el acceso a la tabla MFT", access_error=True)
            if error_code in (ERROR_INVALID_FUNCTION, ERROR_INVALID_PARAMETER):
                self._raise_last_error(
                    "El volumen no admite la enumeración MFT solicitada"
                )
            self._raise_last_error("Falló FSCTL_ENUM_USN_DATA")

        if bytes_returned.value == 0:
            return None
        return output_buffer.raw[:bytes_returned.value]

    def get_file_size_by_id(self, file_hint_handle, file_reference: int) -> int:
        descriptor = _FILE_ID_DESCRIPTOR()
        descriptor.dwSize = ctypes.sizeof(_FILE_ID_DESCRIPTOR)
        descriptor.Type = 0  # FileIdType
        descriptor.FileId = ctypes.c_int64(file_reference).value

        handle = self.kernel32.OpenFileById(
            file_hint_handle,
            ctypes.byref(descriptor),
            FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            None,
            FILE_FLAG_BACKUP_SEMANTICS,
        )
        if handle in (None, ctypes.c_void_p(-1).value):
            self._raise_last_error(
                f"No se pudo abrir por ID el registro MFT {file_reference}"
            )

        try:
            info = _FILE_STANDARD_INFO()
            if not self.kernel32.GetFileInformationByHandleEx(
                handle,
                FILE_STANDARD_INFO_CLASS,
                ctypes.byref(info),
                ctypes.sizeof(info),
            ):
                self._raise_last_error(
                    f"No se pudo obtener el tamaño del registro MFT {file_reference}"
                )
            return max(0, int(info.EndOfFile))
        finally:
            self.close_handle(handle)

def get_volume_info(path: Path) -> VolumeInfo:
    """Función auxiliar a nivel de módulo para obtener información del volumen."""
    return WindowsVolumeApi().get_volume_info(path)


def is_process_elevated() -> bool:
    """Función auxiliar a nivel de módulo para comprobar la elevación del proceso."""
    return WindowsVolumeApi().is_process_elevated()