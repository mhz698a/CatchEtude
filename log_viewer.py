# log_viewer.py
"""
Log Viewer module - UI for viewing application logs in real-time.
Módulo Visor de Registros: interfaz para ver los registros de la aplicación en tiempo real.
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QTabWidget, QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt, pyqtSlot, QTimer
import time
import threading
from log_mgr import get_log_history
import config

_watchdog_thread_logs = {}

class LogViewerWindow(QWidget):
    """
    Window to display application logs organized by level.
    Ventana para mostrar los registros de la aplicación organizados por nivel.
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CatchEtude - Log Viewer")
        self.setWindowIcon(QIcon(config.ICON_PATH))
        self.resize(800, 500)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()

        self.txt_info = QPlainTextEdit()
        self.txt_info.setReadOnly(True)
        self.txt_info.setMaximumBlockCount(1000)

        self.txt_warn = QPlainTextEdit()
        self.txt_warn.setReadOnly(True)
        self.txt_warn.setMaximumBlockCount(1000)

        self.txt_error = QPlainTextEdit()
        self.txt_error.setReadOnly(True)
        self.txt_error.setMaximumBlockCount(1000)

        self.txt_chars = QPlainTextEdit()
        self.txt_chars.setReadOnly(True)
        self.txt_chars.setMaximumBlockCount(1000)
        
        self.txt_overworld = QPlainTextEdit()
        self.txt_overworld.setReadOnly(True)
        self.txt_overworld.setMaximumBlockCount(1000)

        self.tabs.addTab(self.txt_info, "INFO")
        self.tabs.addTab(self.txt_warn, "WARN")
        self.tabs.addTab(self.txt_error, "ERROR")
        self.tabs.addTab(self.txt_chars, "PERSONAJES")
        self.tabs.addTab(self.txt_overworld, "OVERWORLD")

        # Thread list tab
        self.all_threads = {}
        self.process_last_seen = {}

        self.thread_table = QTableWidget()
        self.thread_table.setColumnCount(5)
        self.thread_table.setHorizontalHeaderLabels(["Proceso", "ID Hilo", "Nombre", "Memoria", "Último Registro"])
        self.thread_table.horizontalHeader().setSectionResizeMode(QHeaderView.SectionResizeMode.ResizeToContents)
        self.thread_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.SectionResizeMode.Stretch)
        self.thread_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        self.tabs.addTab(self.thread_table, "HILOS")

        layout.addWidget(self.tabs)
        
        # Load history
        for level, msg in get_log_history():
            self._add_to_ui(level, msg)

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(2000)
        self.refresh_timer.timeout.connect(self._refresh_threads)
        self.refresh_timer.start()

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
        elif level == "OVERWORLD":
            self.txt_overworld.appendPlainText(message)

    def update_process_threads(self, process_name: str, threads_list: list):
        """Updates threads list for a remote process."""
        self.all_threads[process_name] = threads_list
        self.process_last_seen[process_name] = time.time()
        self._refresh_threads()

    def _refresh_threads(self):
        # 1. Collect Watchdog process threads
        threads_info = []
        try:
            size_bytes = threading.stack_size()
            if size_bytes == 0:
                size_bytes = 1024 * 1024  # 1MB on Windows
            size_mb = size_bytes / (1024 * 1024)

            for t in threading.enumerate():
                t_name = t.name
                last_log = _watchdog_thread_logs.get(t_name, "No logs yet")
                threads_info.append({
                    "process": "Watchdog",
                    "ident": t.ident or 0,
                    "name": t_name,
                    "memory": f"{size_mb:.2f} MB",
                    "last_log": last_log
                })
        except Exception:
            pass

        self.all_threads["Watchdog"] = threads_info
        self.process_last_seen["Watchdog"] = time.time()

        # 2. Check timeouts for other processes (6 seconds)
        now = time.time()
        for proc in list(self.all_threads.keys()):
            if proc == "Watchdog":
                continue
            if now - self.process_last_seen.get(proc, 0) > 6.0:
                self.all_threads[proc] = []

        # 3. Populate QTableWidget
        self.thread_table.blockSignals(True)
        self.thread_table.setRowCount(0)
        row_idx = 0
        for proc in sorted(self.all_threads.keys()):
            for t in self.all_threads[proc]:
                self.thread_table.insertRow(row_idx)
                self.thread_table.setItem(row_idx, 0, QTableWidgetItem(t.get("process", proc)))
                self.thread_table.setItem(row_idx, 1, QTableWidgetItem(str(t.get("ident", 0))))
                self.thread_table.setItem(row_idx, 2, QTableWidgetItem(t.get("name", "")))
                self.thread_table.setItem(row_idx, 3, QTableWidgetItem(t.get("memory", "")))
                self.thread_table.setItem(row_idx, 4, QTableWidgetItem(t.get("last_log", "")))
                row_idx += 1
        self.thread_table.blockSignals(False)
