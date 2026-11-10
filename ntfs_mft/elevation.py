"""Launch an isolated, UAC-elevated helper for MFT scanning.

CatchEtude remains unelevated. Only the short-lived helper process receives
the administrator token after the user accepts the Windows UAC prompt.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional

from .errors import (
    ElevationCancelledError,
    ElevationLaunchError,
    MFTScanCancelled,
)
from .scanner import MFTScanResult

SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_HIDE = 0
WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
ERROR_CANCELLED = 1223


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_uint32),
        ("hIcon", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


def _atomic_write_json(path: Path, payload: dict) -> None:
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _pythonw_executable() -> str:
    """Prefer pythonw.exe so an elevation request does not create a console."""
    executable = Path(sys.executable)
    if not getattr(sys, "frozen", False) and executable.name.casefold() == "python.exe":
        candidate = executable.with_name("pythonw.exe")
        if candidate.is_file():
            return str(candidate)
    return str(executable)


def build_helper_launch() -> tuple[str, list[str], str]:
    """Return executable, argv and working directory for this app deployment."""
    app_dir = Path(__file__).resolve().parents[1]
    if getattr(sys, "frozen", False):
        # catchetude.pyw dispatches this private helper mode before importing
        # and starting the regular application services.
        return (
            sys.executable,
            ["--mft-elevated-helper"],
            str(app_dir),
        )

    return (
        _pythonw_executable(),
        ["-m", "ntfs_mft.elevated_worker"],
        str(app_dir),
    )


def _launch_with_uac(executable: str, arguments: list[str], working_directory: str):
    if os.name != "nt":
        raise ElevationLaunchError("La elevación UAC solo está disponible en Windows.")

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(_SHELLEXECUTEINFOW)]
    shell32.ShellExecuteExW.restype = ctypes.c_int
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.GetExitCodeProcess.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)
    ]
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    parameters = subprocess.list2cmdline(arguments)
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = executable
    info.lpParameters = parameters
    info.lpDirectory = working_directory
    info.nShow = SW_HIDE

    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error_code = ctypes.get_last_error()
        if error_code == ERROR_CANCELLED:
            raise ElevationCancelledError("El usuario canceló la solicitud de permisos UAC.")
        detail = ctypes.FormatError(error_code).strip() if error_code else "error desconocido"
        raise ElevationLaunchError(
            f"No se pudo iniciar el escáner MFT elevado (Windows {error_code}: {detail})."
        )

    if not info.hProcess:
        raise ElevationLaunchError(
            "Windows inició la solicitud UAC, pero no devolvió el handle del proceso auxiliar."
        )
    return info.hProcess, kernel32


class ElevatedMFTRunner:
    """Run an MFT helper as administrator and relay progress to the parent UI."""

    def __init__(self, folder_path: Path):
        self.folder_path = Path(folder_path).resolve()

    @staticmethod
    def _read_json(path: Path) -> Optional[dict]:
        try:
            with Path(path).open("r", encoding="utf-8") as stream:
                return json.load(stream)
        except (FileNotFoundError, PermissionError, json.JSONDecodeError, OSError):
            return None

    def run(
        self,
        progress_callback: Optional[Callable[[str, int, int, int], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ) -> MFTScanResult:
        with tempfile.TemporaryDirectory(prefix="catchetude-mft-uac-") as temporary:
            root = Path(temporary)
            request_path = root / "request.json"
            progress_path = root / "progress.json"
            result_path = root / "result.json"
            cancel_path = root / "cancel.request"

            _atomic_write_json(
                request_path,
                {
                    "folder_path": str(self.folder_path),
                    "progress_path": str(progress_path),
                    "result_path": str(result_path),
                    "cancel_path": str(cancel_path),
                },
            )

            executable, base_arguments, working_directory = build_helper_launch()
            if getattr(sys, "frozen", False):
                arguments = base_arguments + ["--request", str(request_path)]
            else:
                arguments = base_arguments + ["--request", str(request_path)]

            process_handle = None
            kernel32 = None
            last_progress = None
            last_progress_read = 0.0
            try:
                process_handle, kernel32 = _launch_with_uac(
                    executable, arguments, working_directory
                )

                while True:
                    if should_stop and should_stop() and not cancel_path.exists():
                        try:
                            cancel_path.touch()
                        except OSError:
                            pass

                    now = time.monotonic()
                    if progress_callback and now - last_progress_read >= 0.1:
                        last_progress_read = now
                        current = self._read_json(progress_path)
                        if current:
                            signature = (
                                current.get("phase"),
                                current.get("processed"),
                                current.get("file_count"),
                                current.get("total_size"),
                            )
                            if signature != last_progress:
                                last_progress = signature
                                progress_callback(
                                    str(signature[0] or "index"),
                                    int(signature[1] or 0),
                                    int(signature[2] or 0),
                                    int(signature[3] or 0),
                                )

                    wait_result = kernel32.WaitForSingleObject(process_handle, 100)
                    if wait_result == WAIT_OBJECT_0:
                        break
                    if wait_result != WAIT_TIMEOUT:
                        raise ElevationLaunchError(
                            f"Falló la espera del proceso MFT elevado (código {wait_result})."
                        )

                result = self._read_json(result_path)
                if not result:
                    exit_code = ctypes.c_uint32()
                    if not kernel32.GetExitCodeProcess(
                        process_handle, ctypes.byref(exit_code)
                    ):
                        exit_code_value = -1
                    else:
                        exit_code_value = int(exit_code.value)
                    raise ElevationLaunchError(
                        "El proceso MFT elevado terminó sin devolver resultados "
                        f"(código de salida {exit_code_value})."
                    )

                if not result.get("ok"):
                    if result.get("cancelled"):
                        raise MFTScanCancelled(result.get("error") or "Escaneo cancelado.")
                    raise ElevationLaunchError(
                        result.get("error") or "El proceso MFT elevado informó un error."
                    )

                return MFTScanResult(
                    file_count=int(result["file_count"]),
                    total_size=int(result["total_size"]),
                    root_entry_count=int(result["root_entry_count"]),
                    inaccessible_count=int(result["inaccessible_count"]),
                    records_scanned=int(result["records_scanned"]),
                )
            finally:
                if process_handle and kernel32:
                    kernel32.CloseHandle(process_handle)
