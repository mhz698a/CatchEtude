"""
Service and lifecycle management for CatchEtude.
Gestión de servicios y ciclo de vida para CatchEtude.
"""

import os
import sys
import logging
import traceback
import json
import win32event
import win32api
from pathlib import Path
from PyQt6.QtNetwork import QLocalSocket

from config import APP_NAME, ERROR_ALREADY_EXISTS, CRASH_REPORT_PATH

def ensure_single_instance():
    """Ensures only one instance of the application is running."""
    mutex = win32event.CreateMutex(None, False, APP_NAME)
    if win32api.GetLastError() == ERROR_ALREADY_EXISTS:
        print("The service is already running")
        sys.exit()
    return mutex

def add_to_startup(name: str, path_to_exe: str, production: bool):
    """Adds the application to Windows startup."""
    if production:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
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

def start_watchdog():
    """Starts the parallel watchdog service using os.startfile."""
    try:
        watchdog_script = str(Path(__file__).resolve().parent / "catch_watchdog.pyw")
        os.startfile(watchdog_script)
        logging.info("Watchdog started via startfile")
    except Exception:
        logging.exception("Failed to start watchdog via startfile")

def start_character_service():
    """Starts the parallel character data service using os.startfile."""
    try:
        service_script = str(Path(__file__).resolve().parent / "character_service.pyw")
        os.startfile(service_script)
        logging.info("Character service started via startfile")
    except Exception:
        logging.exception("Failed to start character service via startfile")

def send_character_service_command(cmd: str, **kwargs):
    """Sends a command to the parallel character service."""
    socket = QLocalSocket()
    socket.connectToServer("CatchEtudeCharacterServer")
    if socket.waitForConnected(200):
        data = {"cmd": cmd}
        data.update(kwargs)
        socket.write(json.dumps(data).encode('utf-8'))
        socket.waitForBytesWritten(200)
        socket.disconnectFromServer()
