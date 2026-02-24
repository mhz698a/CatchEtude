"""
Restart Utility for CatchEtude - GUI version.
Utilidad de reinicio para CatchEtude - versión GUI.
"""

import sys
import os
import time
import subprocess
import traceback
import ctypes
from pathlib import Path
from PyQt6 import QtCore, QtWidgets, QtGui
from config import APP_NAME, ICON_PATH, MYAPPID

class RestartWindow(QtWidgets.QWidget):
    def __init__(self, pid, script_path):
        super().__init__()
        self.pid = pid
        self.script_path = script_path
        
        self.setWindowTitle(f"{APP_NAME} - Restarting")
        self.setWindowIcon(QtGui.QIcon(ICON_PATH))
        self.setFixedSize(400, 150)
        
        # Window flags: stays on top
        self.setWindowFlags(QtCore.Qt.WindowType.WindowStaysOnTopHint | QtCore.Qt.WindowType.WindowTitleHint)

        layout = QtWidgets.QVBoxLayout(self)
        
        self.status_label = QtWidgets.QLabel("Reiniciando CatchEtude...")
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 0) # Indeterminate mode
        layout.addWidget(self.progress_bar)
        
        self.btn_ok = QtWidgets.QPushButton("OK")
        self.btn_ok.setVisible(False)
        self.btn_ok.clicked.connect(QtWidgets.QApplication.quit)
        layout.addWidget(self.btn_ok)
        
        self.error_area = QtWidgets.QPlainTextEdit()
        self.error_area.setReadOnly(True)
        self.error_area.setVisible(False)
        layout.addWidget(self.error_area)

        # Start the restart logic in a background thread
        self.worker = RestartWorker(self.pid, self.script_path)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_finished(self):
        self.status_label.setText("CatchEtude se ha reiniciado con éxito.")
        self.progress_bar.setVisible(False)
        self.btn_ok.setVisible(True)
        self.setFixedSize(400, 120)

    def _on_error(self, err_msg):
        self.status_label.setText("Error al reiniciar CatchEtude")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")
        self.progress_bar.setVisible(False)
        self.error_area.setPlainText(err_msg)
        self.error_area.setVisible(True)
        self.setFixedSize(600, 400)
        self.btn_ok.setVisible(True)

class RestartWorker(QtCore.QThread):
    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(str)
    
    def __init__(self, pid, script_path):
        super().__init__()
        self.pid = pid
        self.script_path = script_path

    def run(self):
        try:
            # 1. Wait for the process to exit
            while True:
                try:
                    os.kill(self.pid, 0)
                except OSError:
                    # Process is gone
                    break
                time.sleep(0.5)

            # 2. Attempt restart
            # Use CREATE_NEW_PROCESS_GROUP (0x00000010). 
            # Avoid DETACHED_PROCESS (0x00000008) in GUI context as it may cause WinError 87.
            if self.script_path.endswith('.pyw'):
                python_exe = sys.executable.replace("python.exe", "pythonw.exe")
                subprocess.Popen([python_exe, self.script_path], 
                                 creationflags=0x00000010)
            else:
                subprocess.Popen([sys.executable, self.script_path], 
                                 creationflags=0x00000010)
            
            self.finished.emit()
        except Exception:
            self.error.emit(traceback.format_exc())

def main():
    if len(sys.argv) < 3:
        return

    pid_to_wait = int(sys.argv[1])
    path_to_restart = sys.argv[2]

    # Set AppUserModelID
    try:
        # Use the same MYAPPID to group with the main application and share the icon
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(MYAPPID)
    except Exception:
        pass

    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon(ICON_PATH))
    
    win = RestartWindow(pid_to_wait, path_to_restart)
    win.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
