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
    def __init__(self):
        super().__init__()
        self.log_viewer = LogViewerWindow()
        self.log_viewer.setWindowTitle("CatchEtude - Watchdog & Logs")
        self.log_viewer.setWindowIcon(QIcon(ICON_PATH))
        
        self.server = QtNetwork.QLocalServer(self)
        self.server.newConnection.connect(self._on_new_connection)
        QtNetwork.QLocalServer.removeServer(LOG_SERVER_NAME)
        if not self.server.listen(LOG_SERVER_NAME):
            print(f"Server could not start: {self.server.errorString()}")
        
        self.monitor_thread = threading.Thread(target=self._monitor_process, daemon=True)
        self.monitor_thread.start()

        self._closing = False
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
                content = msg.get("message")
                self.log_viewer.add_log(level, content)
            elif cmd == "show":
                self.log_viewer.show()
                self.log_viewer.raise_()
                self.log_viewer.activateWindow()
            elif cmd == "quit":
                self._cleanup()
                QtCore.QCoreApplication.quit()
            elif cmd == "update_pid":
                # Deprecated but kept for compatibility during transition
                pass
        except Exception as e:
            print(f"Error reading socket: {e}")
        socket.disconnectFromServer()

    def _monitor_process(self):
        print(f"Monitoring main app via Mutex: {APP_NAME}")
        
        while True:
            try:
                handle = win32event.OpenMutex(win32event.SYNCHRONIZE, False, APP_NAME)
                if handle:
                    # Use WaitForSingleObject to wait efficiently until the mutex is released (app terminates)
                    win32event.WaitForSingleObject(handle, win32event.INFINITE)
                    win32api.CloseHandle(handle)
                    # Main app terminated
                    break
                else:
                    # Main app not running yet, wait and try again
                    time.sleep(1)
            except Exception:
                # Mutex does not exist or cannot be opened, app is likely closed
                break
            
        print("Main process terminated (Mutex signal).")
        self._handle_termination()
        # Exit service
        self._cleanup()
        QtCore.QCoreApplication.quit()

    def _handle_termination(self):
        if CRASH_REPORT_PATH.exists():
            try:
                crash_data = CRASH_REPORT_PATH.read_text(encoding='utf-8')
                self.log_viewer.add_log("ERROR", f"CRASH DETECTED IN MAIN PROCESS:\n{crash_data}")
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
        except Exception:
            pass
        try:
            QtNetwork.QLocalServer.removeServer(LOG_SERVER_NAME)
        except Exception:
            pass

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
    
    # Detect if main service is running
    try:
        handle = win32event.OpenMutex(win32event.SYNCHRONIZE, False, APP_NAME)
        if not handle:
            print("Main app not running, watchdog exiting.")
            return
        win32api.CloseHandle(handle)
    except Exception:
        print("Main app not running, watchdog exiting.")
        return

    service = WatchdogService()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
