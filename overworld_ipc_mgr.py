# overworld_ipc_mgr.py
from __future__ import annotations

import json
import logging
import time
from PyQt6 import QtCore, QtNetwork
from service_mgr import start_overworld_service

OVERWORLD_SERVER_NAME = "CatchEtudeOverworldServer"
OVERWORLD_CLIENT_NAME = "CatchEtudeOverworldClient"

logger = logging.getLogger("overworld.ipc")

class OverworldServiceClient(QtCore.QObject):
    result_ready = QtCore.pyqtSignal(str, str, str)
    finished_ready = QtCore.pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_generation = 0

        self.server = QtNetwork.QLocalServer(self)
        self.server.newConnection.connect(self._on_new_connection)

        QtNetwork.QLocalServer.removeServer(OVERWORLD_CLIENT_NAME)
        if not self.server.listen(OVERWORLD_CLIENT_NAME):
            logger.error("Overworld client server could not start: %s", self.server.errorString())

    def request_overworld(self, year: int, base_path: str, generation: int) -> None:
        self._active_generation = generation

        try:
            start_overworld_service()
        except Exception:
            logger.exception("Failed to ensure Overworld Service is running")

        last_error = ""

        for attempt in range(5):
            server_name = (OVERWORLD_SERVER_NAME or "").strip()
            if not server_name:
                logger.error("Overworld server name is empty")
                return

            socket = QtNetwork.QLocalSocket()
            socket.connectToServer(server_name)

            if not socket.waitForConnected(500):
                last_error = socket.errorString()
                logger.debug(
                    "Attempt %s failed to connect to Overworld Service (%r): %s",
                    attempt + 1,
                    server_name,
                    last_error,
                )
                try:
                    socket.abort()
                except Exception as e:
                    logger.debug(f"Socket abort failed in overworld request: {e}")
                socket.deleteLater()
                time.sleep(0.15)
                continue

            try:
                payload = json.dumps(
                    {
                        "cmd": "load",
                        "year": year,
                        "base_path": base_path,
                        "generation": generation,
                    }
                )
                socket.write(payload.encode("utf-8"))
                if not socket.waitForBytesWritten(500):
                    last_error = socket.errorString()
                    logger.debug(
                        "Attempt %s failed while writing to Overworld Service: %s",
                        attempt + 1,
                        last_error,
                    )
                else:
                    return
            finally:
                try:
                    socket.disconnectFromServer()
                except Exception:
                    logger.debug(f"Socket disconnect in overworld failed: {e}")
                socket.deleteLater()

            time.sleep(0.15)

        logger.error(
            "Failed to connect to Overworld Service (%s): %s",
            OVERWORLD_SERVER_NAME,
            last_error or "unknown error",
        )        
        
    def _on_new_connection(self):
        socket = self.server.nextPendingConnection()
        socket.readyRead.connect(lambda s=socket: self._read_socket(s))

    def _read_socket(self, socket):
        raw = socket.readAll().data().decode("utf-8")
        try:
            msg = json.loads(raw)
            if msg.get("generation") != self._active_generation:
                return

            if msg.get("cmd") == "update":
                self.result_ready.emit(
                    msg.get("name", ""),
                    msg.get("line2", ""),
                    msg.get("line3", ""),
                )
            elif msg.get("cmd") == "finish":
                try:
                    gen = int(msg.get("generation", -1))
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid generation value in overworld message: {msg.get('generation')} ({e})")
                    gen = -1
                except Exception as e:
                    logger.error(f"Unexpected error parsing generation: {e}")
                    gen = -1
                    
                self.finished_ready.emit(gen)
                
        except Exception:
            logger.exception("Error processing overworld update from service")
        finally:
            socket.disconnectFromServer()