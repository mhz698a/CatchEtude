"""
Watchdog and Log Service for CatchEtude.
Servicio de Vigilancia y Registros para CatchEtude.
"""

import logging
import sys
import os
import json
import time
import win32event
import win32api
import ctypes
import subprocess
from pathlib import Path
from PyQt6 import QtCore, QtWidgets, QtNetwork
from PyQt6.QtGui import QIcon
from log_viewer import LogViewerWindow, _watchdog_thread_logs
import config

def log_watchdog(message: str):
    import threading
    t_name = threading.current_thread().name
    _watchdog_thread_logs[t_name] = message
    print(message)

WATCHDOG_NAME = "CatchEtudeWatchdog"
LOG_SERVER_NAME = "CatchEtudeLogServer"
ERROR_ALREADY_EXISTS = 183


class ProcessMonitorThread(QtCore.QThread):
    def __init__(self, service):
        super().__init__()
        self.service = service

    def run(self):
        self.service._monitor_process()


class WatchdogService(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.log_viewer = LogViewerWindow()
        self.log_viewer.setWindowTitle("CatchEtude - Watchdog & Logs")
        self.log_viewer.setWindowIcon(QIcon(config.ICON_PATH))
        
        self.server = QtNetwork.QLocalServer(self)
        self.server.newConnection.connect(self._on_new_connection)
        QtNetwork.QLocalServer.removeServer(LOG_SERVER_NAME)
        if not self.server.listen(LOG_SERVER_NAME):
            log_watchdog(f"Server could not start: {self.server.errorString()}")
        
        self.monitor_thread = ProcessMonitorThread(self)
        self.monitor_thread.start()

        self._closing = False
        self._restart_sent = False
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._cleanup)

    def _on_new_connection(self):
        socket = self.server.nextPendingConnection()
        socket.readyRead.connect(lambda: self._read_socket(socket))

    def _read_socket(self, socket):
        data = socket.readAll().data().decode('utf-8')
        try:
            msg = json.loads(data)
            cmd = msg.get("cmd")
            if cmd == "log":
                level = msg.get("level")
                logger_name = msg.get("logger", "")
                if logger_name.startswith("overworld") and level not in ("WARN", "WARNING", "ERROR", "CRITICAL"):
                    level = "OVERWORLD"
                content = msg.get("message")
                self.log_viewer.add_log(level, content)
            elif cmd == "threads":
                process_name = msg.get("process")
                threads_list = msg.get("threads", [])
                self.log_viewer.update_process_threads(process_name, threads_list)
            elif cmd == "show":
                self.log_viewer.show()
                self.log_viewer.raise_()
                self.log_viewer.activateWindow()
            elif cmd == "quit":
                log_watchdog("Watchdog Service: Quit request received. Sending OK response.")
                # 1. Responder al cliente que todo está listo antes de apagar
                socket.write(json.dumps({"status": "ok"}).encode('utf-8'))
                socket.flush()
                # 2. Desconectarse, limpiar y cerrar el loop de Qt
                socket.disconnectFromServer()
                self._cleanup()
                QtCore.QCoreApplication.quit()
                return  # Salimos de inmediato para no repetir el disconnect posterior
            elif cmd == "update_pid":
                # Deprecated but kept for compatibility during transition
                pass
        except Exception as e:
            log_watchdog(f"Error reading socket: {e}")
        socket.disconnectFromServer()

    def _monitor_process(self):
        log_watchdog(f"Monitoring main app via Mutex: {config.APP_NAME}")
        
        while True:
            try:
                handle = win32event.OpenMutex(win32event.SYNCHRONIZE, False, config.APP_NAME)
                if handle:
                    # Use WaitForSingleObject to wait efficiently until the mutex is released (app terminates)
                    win32event.WaitForSingleObject(handle, win32event.INFINITE)
                    win32api.CloseHandle(handle)
                    # Main app terminated
                    break
                else:
                    # Main app not running yet, wait and try again
                    time.sleep(1)
            except Exception as e:
                logging.debug(f"Mutex check failed (app likely closed): {e}")
                # Mutex does not exist or cannot be opened, app is likely closed
                break
            
        # Exit Service
        log_watchdog("Main process terminated (Mutex signal).")
        self._handle_termination()
        self._launch_restart()
            
        self._cleanup()
        QtCore.QCoreApplication.quit()

    def _handle_termination(self):
        if config.CRASH_REPORT_PATH.exists():
            try:
                crash_data = config.CRASH_REPORT_PATH.read_text(encoding='utf-8')
                self.log_viewer.add_log("ERROR", f"CRASH DETECTED IN MAIN PROCESS:\n{crash_data}")
                
                try:
                    if config.CRASH_REPORT_PATH.exists():
                        config.CRASH_REPORT_PATH.unlink()
                except FileNotFoundError:
                    deleted = 1
                except PermissionError:
                    logging.warning(f"Cannot delete old crash report: {config.CRASH_REPORT_PATH}")
                except Exception as e:
                    logging.warning(f"Error deleting crash report: {e}")
                
                # Show window on crash
                QtCore.QMetaObject.invokeMethod(self.log_viewer, "show", QtCore.Qt.ConnectionType.QueuedConnection)
            except Exception as e:
                print(f"Error reading crash report: {e}")

    def _cleanup(self):
        if self._closing:
            return
        self._closing = True
        try:
            if self.server.isListening():
                self.server.close()
        except Exception as e:
            logging.debug(f"Error closing server during cleanup: {e}")
    
        try:
            QtNetwork.QLocalServer.removeServer(LOG_SERVER_NAME)
        except Exception as e:
            logging.debug(f"Error removing server from registry: {e}")

    def _pythonw_executable(self) -> str:
        exe = Path(sys.executable)
        if exe.name.lower() == "python.exe":
            candidate = exe.with_name("pythonw.exe")
            if candidate.exists():
                return str(candidate)
        return sys.executable

    def _launch_restart(self):
        if self._restart_sent:
            return
        self._restart_sent = True

        try:
            # No cambiar a py sin permisos del autor
            main_script = str(Path(__file__).resolve().parent / "catchetude.pyw")

            subprocess.Popen(
                [self._pythonw_executable(), config.RESTART_APP_DIR, str(os.getpid()), main_script],
                creationflags=0x00000010,
            )
            print("Restart helper launched.")
        except Exception:
            print("Failed to launch restart helper")

def main():
    # Set AppUserModelID for Windows Taskbar icon grouping
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(config.MYAPPID)
    except OSError as e:
        logging.debug(f"Failed to set AppUserModelID (Windows integration): {e}")
    except Exception as e:
        logging.debug(f"Unexpected error setting AppUserModelID: {e}")

    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QIcon(config.ICON_PATH))
    app.setQuitOnLastWindowClosed(False)

    # Ensure single instance
    mutex = win32event.CreateMutex(None, False, WATCHDOG_NAME)
    if win32api.GetLastError() == ERROR_ALREADY_EXISTS:
        # If already running, and we have a "show" arg, signal it?
        # For now, just exit.
        return
    
    service = WatchdogService()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
