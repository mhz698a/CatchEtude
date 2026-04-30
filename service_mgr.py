"""
Service and lifecycle management for CatchEtude.
Gestión de servicios y ciclo de vida para CatchEtude.
"""

import os
import sys
import logging
import traceback
import json
import time
import subprocess
import win32event
import win32api
from pathlib import Path
from PyQt6.QtNetwork import QLocalSocket
from PyQt6.QtWidgets import QMessageBox

from config import APP_NAME, ERROR_ALREADY_EXISTS, CRASH_REPORT_PATH

WATCHDOG_SERVER_NAME = "CatchEtudeLogServer"
CHARACTER_SERVER_NAME = "CatchEtudeCharacterServer"
WATCHDOG_MUTEX_NAME = "CatchEtudeWatchdog"
CHARACTER_MUTEX_NAME = "CatchEtudeCharacterServiceMutex"
CREATE_NEW_PROCESS_GROUP = 0x00000010

def ensure_single_instance():
    """Ensures only one instance of the application is running."""
    # Standard local mutex to avoid permission issues with Global\.
    # bInitialOwner=True so the main app owns it and it remains non-signaled for waiters.
    mutex = win32event.CreateMutex(None, True, APP_NAME)
    if win32api.GetLastError() == ERROR_ALREADY_EXISTS:
        QMessageBox.warning(
            None,
            APP_NAME,
            "CatchEtude ya está abierta.\n\n"
            "Usa la ventana existente o el icono de la bandeja."
        )
        sys.exit()
    return mutex

def add_to_startup(name: str, path_to_exe: str, production: bool):
    """Adds the application to Windows startup."""
    if production:
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_SET_VALUE
            )
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, f"\"{path_to_exe}\"")
            winreg.CloseKey(key)
            logging.info("Added to Windows startup")
        except Exception:
            logging.exception("Failed to add to startup")

def crash_handler(etype, value, tb):
    """Global exception hook to record crashes."""
    err_msg = "".join(traceback.format_exception(etype, value, tb))
    logging.critical(f"Unhandled exception:\n{err_msg}")
    try:
        CRASH_REPORT_PATH.write_text(err_msg, encoding='utf-8')
    except Exception:
        pass
    
    # Launch crash dialog via os.startfile
    try:
        crash_dialog_script = str(Path(__file__).resolve().parent / "crash_dialog.pyw")
        os.startfile(crash_dialog_script)
    except Exception:
        logging.exception("Failed to launch crash dialog")

def _mutex_exists(name: str) -> bool:
    handle = None
    try:
        handle = win32event.OpenMutex(win32event.SYNCHRONIZE, False, name)
        return True
    except Exception:
        return False
    finally:
        if handle:
            try:
                win32api.CloseHandle(handle)
            except Exception:
                pass

def _server_alive(server_name: str, timeout_ms: int = 150) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if socket.waitForConnected(timeout_ms):
        try:
            socket.disconnectFromServer()
        except Exception:
            pass
        return True
    return False

def _send_quit(server_name: str, timeout_ms: int = 1000) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(timeout_ms):
        return False
    try:
        socket.write(json.dumps({"cmd": "quit"}).encode("utf-8"))
        socket.waitForBytesWritten(timeout_ms)
    finally:
        try:
            socket.disconnectFromServer()
        except Exception:
            pass
    return True

def wait_for_services_stopped(timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        watchdog_up = _mutex_exists(WATCHDOG_MUTEX_NAME) or _server_alive(WATCHDOG_SERVER_NAME, 100)
        char_up = _mutex_exists(CHARACTER_MUTEX_NAME) or _server_alive(CHARACTER_SERVER_NAME, 100)
        if not watchdog_up and not char_up:
            return True
        time.sleep(0.1)
    return False

def stop_parallel_services(timeout: float = 8.0) -> bool:
    """Sends quit to both services and waits until they are really gone."""
    _send_quit(WATCHDOG_SERVER_NAME)
    _send_quit(CHARACTER_SERVER_NAME)
    return wait_for_services_stopped(timeout)

def _pythonw_executable() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return sys.executable

def _launch_python_script(script_name: str) -> None:
    script_path = str(Path(__file__).resolve().parent / script_name)
    subprocess.Popen(
        [_pythonw_executable(), script_path],
        creationflags=CREATE_NEW_PROCESS_GROUP
    )

def start_watchdog():
    """Starts the parallel watchdog service."""
    try:
        if _mutex_exists(WATCHDOG_MUTEX_NAME) or _server_alive(WATCHDOG_SERVER_NAME, 100):
            logging.info("Watchdog already running")
            return
        _launch_python_script("catch_watchdog.pyw")
        logging.info("Watchdog started")
    except Exception:
        logging.exception("Failed to start watchdog")

def start_character_service():
    """Starts the parallel character data service."""
    try:
        if _mutex_exists(CHARACTER_MUTEX_NAME) or _server_alive(CHARACTER_SERVER_NAME, 100):
            logging.info("Character service already running")
            return
        _launch_python_script("character_service.pyw")
        logging.info("Character service started")
    except Exception:
        logging.exception("Failed to start character service")
        
def send_character_service_command(cmd: str, **kwargs):
    """Sends a command to the parallel character service."""
    socket = QLocalSocket()
    socket.connectToServer(CHARACTER_SERVER_NAME)
    if socket.waitForConnected(200):
        data = {"cmd": cmd}
        data.update(kwargs)
        socket.write(json.dumps(data).encode('utf-8'))
        socket.waitForBytesWritten(200)
        socket.disconnectFromServer()
