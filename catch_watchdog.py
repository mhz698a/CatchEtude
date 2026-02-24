"""
Watchdog and Log Service for CatchEtude.
Servicio de Vigilancia y Registros para CatchEtude.
"""

import sys
import os
import json
import time
import threading
import win32event
import win32api
import ctypes
from pathlib import Path
from PyQt6 import QtCore, QtWidgets, QtNetwork
from PyQt6.QtGui import QIcon
from log_viewer import LogViewerWindow
from config import APP_NAME, CRASH_REPORT_PATH, ICON_PATH, MYAPPID

WATCHDOG_NAME = "CatchEtudeWatchdog"
LOG_SERVER_NAME = "CatchEtudeLogServer"
ERROR_ALREADY_EXISTS = 183

class WatchdogService(QtCore.QObject):
    def __init__(self, main_pid: int):
        super().__init__()
        self.main_pid = main_pid
        self.log_viewer = LogViewerWindow()
        self.log_viewer.setWindowTitle("CatchEtude - Watchdog & Logs")
        self.log_viewer.setWindowIcon(QIcon(ICON_PATH))
        
        self.server = QtNetwork.QLocalServer(self)
        self.server.newConnection.connect(self._on_new_connection)
        QtNetwork.QLocalServer.removeServer(LOG_SERVER_NAME)
        if not self.server.listen(LOG_SERVER_NAME):
            print(f"Server could not start: {self.server.errorString()}")
        
        self.monitor_thread = None
        if self.main_pid:
            self._start_monitor()

    def _start_monitor(self):
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
        self.monitor_thread = threading.Thread(target=self._monitor_process, daemon=True)
        self.monitor_thread.start()

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
                content = msg.get("message")
                self.log_viewer.add_log(level, content)
            elif cmd == "show":
                self.log_viewer.show()
                self.log_viewer.raise_()
                self.log_viewer.activateWindow()
            elif cmd == "update_pid":
                new_pid = msg.get("pid")
                print(f"Updating monitored PID to: {new_pid}")
                self.main_pid = new_pid
                self._start_monitor()
        except Exception as e:
            print(f"Error reading socket: {e}")
        socket.disconnectFromServer()

    def _monitor_process(self):
        print(f"Monitoring PID: {self.main_pid}")
        while True:
            current_pid = self.main_pid
            if not current_pid:
                time.sleep(1)
                continue
                
            try:
                # Check if process exists
                os.kill(current_pid, 0)
            except OSError:
                # Process terminated
                # Check if it was updated in the meantime
                if self.main_pid != current_pid:
                    continue
                    
                print(f"Main process {current_pid} terminated.")
                self._handle_termination()
                break
            time.sleep(1)

    def _handle_termination(self):
        if CRASH_REPORT_PATH.exists():
            try:
                crash_data = CRASH_REPORT_PATH.read_text(encoding='utf-8')
                self.log_viewer.add_log("ERROR", f"CRASH DETECTED IN MAIN PROCESS:\n{crash_data}")
                # Show window on crash
                QtCore.QMetaObject.invokeMethod(self.log_viewer, "show", QtCore.Qt.ConnectionType.QueuedConnection)
            except Exception as e:
                print(f"Error reading crash report: {e}")

def main():
    # Set AppUserModelID for Windows Taskbar icon grouping
    try:
        # Use the same MYAPPID to group with the main application and share the icon
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(MYAPPID)
    except Exception:
        pass

    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QIcon(ICON_PATH))
    app.setQuitOnLastWindowClosed(False)

    # Ensure single instance
    mutex = win32event.CreateMutex(None, False, WATCHDOG_NAME)
    if win32api.GetLastError() == ERROR_ALREADY_EXISTS:
        # If already running, and we have a "show" arg, signal it?
        # For now, just exit.
        return

    main_pid = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    service = WatchdogService(main_pid)
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
