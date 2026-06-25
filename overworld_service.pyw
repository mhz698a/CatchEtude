# overworld_service.pyw
from __future__ import annotations

import ctypes
import json
import logging
import sys
import traceback
from pathlib import Path

import win32api
import win32event
from PyQt6 import QtCore, QtNetwork

from config import APP_NAME, CRASH_REPORT_PATH, MYAPPID
from overworld_cache_mgr import OverworldCacheManager
from overworld_scanner_mgr import OverworldScanner
from overworld_ipc_mgr import OVERWORLD_CLIENT_NAME, OVERWORLD_SERVER_NAME

logger = logging.getLogger("overworld.service")

SERVICE_MUTEX_NAME = "CatchEtudeOverworldServiceMutex"
ERROR_ALREADY_EXISTS = 183


def crash_handler(etype, value, tb):
    err_msg = "".join(traceback.format_exception(etype, value, tb))
    logger.critical(f"Unhandled exception in OverworldService:\n{err_msg}")
    try:
        CRASH_REPORT_PATH.write_text(f"OVERWORLD_SERVICE_CRASH:\n{err_msg}", encoding="utf-8")
    except Exception:
        pass
    
    # --- NUEVO: Cuadro de mensaje nativo de Windows antes de morir ---
    try:
        # MB_ICONERROR (0x10) | MB_SYSTEMMODAL (0x1000) para forzar que salga al frente
        ctypes.windll.user32.MessageBoxW(
            0, 
            f"El servicio Overworld ha fallado.\n\nError: {value}\n\nSe ha guardado un reporte en el log.", 
            "Error Crítico - Overworld Service", 
            0x10 | 0x1000
        )
    except Exception:
        pass
    
    sys.exit(1)


class OverworldService(QtCore.QObject):
    update_ready = QtCore.pyqtSignal(int, str, str, str)

    def __init__(self):
        super().__init__()
        self._closing = False
        self._active_generation = 0
        self._scanner = None

        self.server = QtNetwork.QLocalServer(self)
        self.server.newConnection.connect(self._on_new_connection)
        QtNetwork.QLocalServer.removeServer(OVERWORLD_SERVER_NAME)
        if not self.server.listen(OVERWORLD_SERVER_NAME):
            logger.error("Overworld Service could not start: %s", self.server.errorString())

        self.update_ready.connect(self._send_update)

        self._monitor_timer = QtCore.QTimer(self)
        self._monitor_timer.timeout.connect(self._check_main_process)
        self._monitor_timer.start(2000)

        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._cleanup)

    def _check_main_process(self):
        handle = None
        try:
            handle = win32event.OpenMutex(win32event.SYNCHRONIZE, False, APP_NAME)
            if handle:
                win32api.CloseHandle(handle)
                return
        except Exception:
            pass

        self._cleanup()
        QtCore.QCoreApplication.quit()

    def _on_new_connection(self):
        socket = self.server.nextPendingConnection()
        socket.readyRead.connect(lambda s=socket: self._read_socket(s))

    def _read_socket(self, socket):
        raw = socket.readAll().data().decode("utf-8")
        try:
            msg = json.loads(raw)
            cmd = msg.get("cmd")

            if cmd == "load":
                year = int(msg.get("year"))
                generation = int(msg.get("generation", 0))
                base_path = Path(msg.get("base_path"))
                self._start_scan(base_path, year, generation)
                
                logger.info(
                    "Scan request year=%s generation=%s path=%s",
                    year,
                    generation,
                    base_path,
                )

            elif cmd == "quit":
                self._cleanup()
                QtCore.QCoreApplication.quit()
        except Exception:
            logger.exception("Error reading Overworld Service socket")
        finally:
            socket.disconnectFromServer()

    def _start_scan(self, base_path: Path, year: int, generation: int):
        self._active_generation = generation

        if self._scanner is not None:
            try:
                self._scanner.abort()
                self._scanner.wait()
            except Exception:
                pass

        cache = OverworldCacheManager(year)
        self._scanner = OverworldScanner(base_path, cache)
        self._scanner.result_ready.connect(
            lambda name, line2, line3, gen=generation: self.update_ready.emit(gen, name, line2, line3)
        )
        self._scanner.finished.connect(lambda: self._on_scan_finished(generation))
        self._scanner.start()
        
        logger.info(
            "Scanner started generation=%s",
            generation,
        )

    def _send_update(self, generation: int, name: str, line2: str, line3: str):
        if self._closing or generation != self._active_generation:
            return

        socket = QtNetwork.QLocalSocket()
        socket.connectToServer(OVERWORLD_CLIENT_NAME)
        logger.debug(
            "Sending update: %s",
            name,
        )
        if not socket.waitForConnected(300):
            return

        payload = json.dumps(
            {
                "cmd": "update",
                "generation": generation,
                "name": name,
                "line2": line2,
                "line3": line3,
            }
        )
        socket.write(payload.encode("utf-8"))
        socket.waitForBytesWritten(300)
        socket.disconnectFromServer()

    def _on_scan_finished(self, generation: int):
        if generation == self._active_generation:
            logger.info("Overworld scan finished for generation %s", generation)
        self._scanner = None

    def _cleanup(self):
        if self._closing:
            return

        self._closing = True
        try:
            if self._scanner is not None:
                self._scanner.abort()
        except Exception:
            pass

        try:
            if self.server.isListening():
                self.server.close()
        except Exception:
            pass

        try:
            QtNetwork.QLocalServer.removeServer(OVERWORLD_SERVER_NAME)
        except Exception:
            pass


def main():
    sys.excepthook = crash_handler

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(MYAPPID)
    except Exception:
        pass

    mutex = win32event.CreateMutex(None, False, SERVICE_MUTEX_NAME)
    if win32api.GetLastError() == ERROR_ALREADY_EXISTS:
        return

    try:
        handle = win32event.OpenMutex(win32event.SYNCHRONIZE, False, APP_NAME)
        if not handle:
            return
        win32api.CloseHandle(handle)
    except Exception:
        return

    app = QtCore.QCoreApplication(sys.argv)
    service = OverworldService()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()