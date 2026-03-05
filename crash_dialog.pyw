"""
Crash Dialog for CatchEtude.
Shows error details and provides a restart button.
"""

import sys
import os
import ctypes
from pathlib import Path
from PyQt6 import QtWidgets, QtCore, QtGui
from config import APP_NAME, ICON_PATH, MYAPPID, CRASH_REPORT_PATH
from localization import LocalizationManager

class CrashDialog(QtWidgets.QDialog):
    def __init__(self, traceback_text):
        super().__init__(None, QtCore.Qt.WindowType.WindowStaysOnTopHint | QtCore.Qt.WindowType.Tool)
        self.loc = LocalizationManager()
        self.traceback_text = traceback_text
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle(self.loc.get("crash_title"))
        self.setWindowIcon(QtGui.QIcon(ICON_PATH))
        self.setFixedSize(600, 450)

        layout = QtWidgets.QVBoxLayout(self)

        # Icon and Message
        header_layout = QtWidgets.QHBoxLayout()
        icon_label = QtWidgets.QLabel()
        error_icon = self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_MessageBoxCritical)
        icon_label.setPixmap(error_icon.pixmap(48, 48))
        header_layout.addWidget(icon_label)

        msg_label = QtWidgets.QLabel(self.loc.get("crash_msg"))
        msg_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        msg_label.setWordWrap(True)
        header_layout.addWidget(msg_label, 1)
        layout.addLayout(header_layout)

        # Traceback area
        layout.addWidget(QtWidgets.QLabel(self.loc.get("lbl_traceback")))
        self.txt_traceback = QtWidgets.QPlainTextEdit()
        self.txt_traceback.setReadOnly(True)
        self.txt_traceback.setPlainText(self.traceback_text)
        self.txt_traceback.setStyleSheet("font-family: Consolas, monospace; font-size: 10pt;")
        layout.addWidget(self.txt_traceback)

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()

        self.btn_restart = QtWidgets.QPushButton(self.loc.get("btn_restart_service"))
        self.btn_restart.setIcon(self.style().standardIcon(QtWidgets.QStyle.StandardPixmap.SP_BrowserReload))
        self.btn_restart.setFixedHeight(35)
        self.btn_restart.setFixedWidth(150)
        self.btn_restart.clicked.connect(self._on_restart)
        btn_layout.addWidget(self.btn_restart)

        self.btn_close = QtWidgets.QPushButton(self.loc.get("tray_exit"))
        self.btn_close.setFixedHeight(35)
        self.btn_close.clicked.connect(self.close)
        btn_layout.addWidget(self.btn_close)

        layout.addLayout(btn_layout)

    def _on_restart(self):
        # Path to catchetude.pyw
        main_script = str(Path(__file__).resolve().parent / "catchetude.pyw")
        try:
            os.startfile(main_script)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Could not restart: {e}")
        self.accept()

def main():
    # Set AppUserModelID
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(MYAPPID)
    except Exception:
        pass

    app = QtWidgets.QApplication(sys.argv)

    traceback_text = "No traceback available."
    if CRASH_REPORT_PATH.exists():
        try:
            traceback_text = CRASH_REPORT_PATH.read_text(encoding='utf-8')
        except Exception:
            pass

    dialog = CrashDialog(traceback_text)
    dialog.exec()

if __name__ == "__main__":
    main()
