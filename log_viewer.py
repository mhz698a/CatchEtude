"""
Log Viewer module - UI for viewing application logs in real-time.
Módulo Visor de Registros: interfaz para ver los registros de la aplicación en tiempo real.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QPlainTextEdit
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, pyqtSlot
from log_mgr import get_log_history
from config import ICON_PATH

class LogViewerWindow(QWidget):
    """
    Window to display application logs organized by level.
    Ventana para mostrar los registros de la aplicación organizados por nivel.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CatchEtude - Log Viewer")
        self.setWindowIcon(QIcon(ICON_PATH))
        self.resize(700, 500)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        self.txt_info = QPlainTextEdit()
        self.txt_info.setReadOnly(True)

        self.txt_warn = QPlainTextEdit()
        self.txt_warn.setReadOnly(True)

        self.txt_error = QPlainTextEdit()
        self.txt_error.setReadOnly(True)

        self.txt_chars = QPlainTextEdit()
        self.txt_chars.setReadOnly(True)

        self.tabs.addTab(self.txt_info, "INFO")
        self.tabs.addTab(self.txt_warn, "WARN")
        self.tabs.addTab(self.txt_error, "ERROR")
        self.tabs.addTab(self.txt_chars, "PERSONAJES")

        layout.addWidget(self.tabs)
        
        # Load history
        for level, msg in get_log_history():
            self._add_to_ui(level, msg)

    def closeEvent(self, event):
        """Hides the window instead of closing it."""
        event.ignore()
        self.hide()

    @pyqtSlot(str, str)
    def add_log(self, level: str, message: str):
        """Adds a new log message to the appropriate tab."""
        self._add_to_ui(level, message)
        
        if level == "ERROR":
            # Switch to ERROR tab and show window if an error occurs
            self.tabs.setCurrentIndex(2)
            if not self.isVisible():
                self.show()
                self.raise_()
                self.activateWindow()

    def _add_to_ui(self, level: str, message: str):
        if level == "INFO":
            self.txt_info.appendPlainText(message)
        elif level == "WARN":
            self.txt_warn.appendPlainText(message)
        elif level == "ERROR":
            self.txt_error.appendPlainText(message)
        elif level == "CHARS":
            self.txt_chars.appendPlainText(message)
