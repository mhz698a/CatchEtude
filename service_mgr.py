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

import config

WATCHDOG_SERVER_NAME = "CatchEtudeLogServer"
CHARACTER_SERVER_NAME = "CatchEtudeCharacterServer"
WATCHDOG_MUTEX_NAME = "CatchEtudeWatchdog"
CHARACTER_MUTEX_NAME = "CatchEtudeCharacterServiceMutex"
OVERWORLD_SERVER_NAME = "CatchEtudeOverworldServer"
OVERWORLD_MUTEX_NAME = "CatchEtudeOverworldServiceMutex"
CREATE_NEW_PROCESS_GROUP = 0x00000010

def ensure_single_instance():
    """Ensures only one instance of the application is running."""
    # Standard local mutex to avoid permission issues with Global\.
    # bInitialOwner=True so the main app owns it and it remains non-signaled for waiters.
    mutex = win32event.CreateMutex(None, True, config.APP_NAME)
    if win32api.GetLastError() == config.ERROR_ALREADY_EXISTS:
        QMessageBox.warning(
            None,
            config.APP_NAME,
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
        config.CRASH_REPORT_PATH.write_text(err_msg, encoding='utf-8')
        logging.info(f"Crash report saved to: {config.CRASH_REPORT_PATH}")
    except IOError as e:
        logging.error(f"Failed to save crash report (IO error): {e}")
    except PermissionError:
        logging.error(f"Permission denied writing crash report: {config.CRASH_REPORT_PATH}")
    except Exception as e:
        logging.error(f"Unexpected error saving crash report: {e}")
    
    # Launch crash dialog via subprocess using pythonw
    try:
        crash_dialog_script = str(Path(__file__).resolve().parent / "crash_dialog.pyw")
        subprocess.Popen(
            [_pythonw_executable(), crash_dialog_script],
            creationflags=CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
        )
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
            except OSError as e:
                logging.debug(f"Failed to close mutex handle: {e}")
            except Exception as e:
                logging.warning(f"Unexpected error closing mutex handle: {e}")

def _server_alive(server_name: str, timeout_ms: int = 150) -> bool:
    socket = _connect_local_socket(server_name, timeout_ms)
    if socket is None:
        return False
    try:
        socket.disconnectFromServer()
    except Exception as e:
        logging.debug(f"Socket disconnect failed in _server_alive: {e}")
    return True


def _connect_local_socket(server_name: str, timeout_ms: int):
    name = (server_name or "").strip()
    if not name:
        logging.error("Local socket name is empty")
        return None

    socket = QLocalSocket()
    socket.connectToServer(name)

    if not socket.waitForConnected(timeout_ms):
        logging.debug("Could not connect to %r: %s", name, socket.errorString())
        try:
            socket.abort()
        except Exception as e:
            logging.debug(f"Socket abort failed: {e}")
        return None

    return socket

def _wait_for_server(server_name: str, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _server_alive(server_name, 200):
            return True
        time.sleep(0.1)
    return False

def wait_for_services_stopped(timeout: float = 8.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        watchdog_up = _mutex_exists(WATCHDOG_MUTEX_NAME) or _server_alive(WATCHDOG_SERVER_NAME, 100)
        char_up = _mutex_exists(CHARACTER_MUTEX_NAME) or _server_alive(CHARACTER_SERVER_NAME, 100)
        overworld_up = _mutex_exists(OVERWORLD_MUTEX_NAME) or _server_alive(OVERWORLD_SERVER_NAME, 100)
        if not watchdog_up and not char_up and not overworld_up:
            return True
        time.sleep(0.1)
    return False

def _force_kill_helper_scripts() -> None:
    """Fallback si el apagado amable no logró cerrar los helpers."""
    try:
        ps_cmd = (
            "$targets = Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine -match 'catch_watchdog\.pyw|character_service\.pyw|overworld_service\.pyw' }; "
            "foreach ($p in $targets) { "
            "Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue "
            "}"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            creationflags=CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        logging.error("PowerShell not found, cannot force kill helpers")
    except subprocess.TimeoutExpired:
        logging.error("Force kill helper script timed out after 10 seconds")
    except Exception as e:
        logging.exception(f"Forced cleanup of helper scripts failed ({type(e).__name__}): {e}")

def stop_parallel_services(timeout: float = 8.0) -> bool:
    """Intentos con backoff y luego forzar kill si no se apagan."""
    # intentos progresivos
    start = time.time()
    backoff = 0.1
    deadline = start + timeout

    # pedir quit a cada servicio con ACK
    for server in (WATCHDOG_SERVER_NAME, CHARACTER_SERVER_NAME, OVERWORLD_SERVER_NAME):
        for attempt in range(4):
            if _send_quit_with_ack(server, timeout_ms=int(500 + 500*attempt)):
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 1.0)

    # esperar que se apaguen (reutiliza wait_for_services_stopped)
    if wait_for_services_stopped(timeout):
        return True

    # fallback: forzar kill y volver a esperar
    _force_kill_helper_scripts()
    return wait_for_services_stopped(max(2.0, timeout/2))

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
        creationflags=CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW,
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

def _send_quit(server_name: str, timeout_ms: int = 1000) -> bool:
    socket = _connect_local_socket(server_name, timeout_ms)
    if socket is None:
        return False
    try:
        socket.write(json.dumps({"cmd": "quit"}).encode("utf-8"))
        socket.waitForBytesWritten(timeout_ms)
    finally:
        try:
            socket.disconnectFromServer()
        except Exception as e:
            logging.debug(f"Socket disconnect in _send_quit failed: {e}")
    return True

def start_overworld_service():
    """Starts the parallel overworld data service."""
    try:
        if _mutex_exists(OVERWORLD_MUTEX_NAME) or _server_alive(OVERWORLD_SERVER_NAME, 100):
            logging.info("Overworld service already running")
            return

        _launch_python_script("overworld_service.pyw")

        if not _wait_for_server(OVERWORLD_SERVER_NAME, 5.0):
            logging.warning("Overworld service started but did not become ready in time")
            return

        logging.info("Overworld service started")
    except Exception:
        logging.exception("Failed to start overworld service")
        
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

def _send_quit_with_ack(server_name: str, timeout_ms: int = 1000) -> bool:
    """Enviar quit y esperar ack (JSON {'status':'ok'})"""
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(timeout_ms):
        try:
            socket.abort()
        except Exception as e:
            logging.debug(f"Socket disconnect failed in _server_alive: {e}")
        return False

    try:
        data = json.dumps({"cmd": "quit"}).encode("utf-8")
        socket.write(data)
        socket.waitForBytesWritten(timeout_ms)

        # esperar respuesta breve
        if socket.waitForReadyRead(timeout_ms):
            resp = bytes(socket.readAll()).decode("utf-8", errors="ignore")
            try:
                j = json.loads(resp)
                return j.get("status") in ("ok", "shutting_down")
            except Exception:
                return False
        return False
    finally:
        try:
            socket.disconnectFromServer()
        except Exception as e:
            logging.debug(f"Socket disconnect failed in _server_alive: {e}")