"""
Restart Utility for CatchEtude - GUI version.
Utilidad de reinicio para CatchEtude - versión GUI.
"""

import logging
import sys
import os
import time
import subprocess
import traceback
import ctypes
import win32event
import win32api
import config
from pathlib import Path
from PyQt6 import QtCore, QtWidgets, QtGui
from service_mgr import stop_parallel_services, wait_for_services_stopped

class RestartWindow(QtWidgets.QWidget):
    def __init__(self, pid, script_path):
        super().__init__()
        self.pid = pid
        self.script_path = script_path
        self._drag_pos = None

        self.setWindowTitle(f"{config.APP_NAME} - Restarting")
        self.setWindowIcon(QtGui.QIcon(config.ICON_PATH))
        self.setWindowFlags(
            QtCore.Qt.WindowType.FramelessWindowHint |
            QtCore.Qt.WindowType.WindowStaysOnTopHint |
            QtCore.Qt.WindowType.Tool
        )
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.setFixedSize(500, 110)

        # Container Widget for styling
        self.container = QtWidgets.QWidget(self)
        self.container.setObjectName("container")
        self.container.setStyleSheet("""
            QWidget#container {
                background-color: #0d1b2a;
                border: 4px solid #1d3557;
                border-radius: 12px;
            }
            QLabel {
                color: #e0e1dd;
                font-size: 13px;
                font-weight: bold;
            }
            QProgressBar {
                border: 1px solid #457b9d;
                border-radius: 4px;
                background-color: #1b263b;
                text-align: center;
                color: white;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: #457b9d;
                width: 15px;
            }
            QPushButton {
                background-color: #1d3557;
                color: #f1faee;
                border: 1px solid #457b9d;
                border-radius: 4px;
                padding: 4px 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #457b9d;
            }
            QPlainTextEdit {
                background-color: #1b263b;
                color: #ff6b6b;
                border: 1px solid #e63946;
                border-radius: 4px;
            }
        """)

        main_layout = QtWidgets.QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)

        container_layout = QtWidgets.QHBoxLayout(self.container)
        container_layout.setContentsMargins(10, 10, 15, 10)
        container_layout.setSpacing(10)

        # Left Drag Handle Gap
        self.drag_gap = QtWidgets.QLabel("⋮\n⋮")
        self.drag_gap.setFixedWidth(20)
        self.drag_gap.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.drag_gap.setStyleSheet("color: #457b9d; font-size: 16px; font-weight: bold; cursor: openhand;")
        container_layout.addWidget(self.drag_gap)

        # Content Layout
        content_layout = QtWidgets.QVBoxLayout()
        content_layout.setSpacing(6)

        self.status_label = QtWidgets.QLabel("Reiniciando CatchEtude...")
        self.status_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter)
        content_layout.addWidget(self.status_label)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 0) # Indeterminate mode
        content_layout.addWidget(self.progress_bar)

        self.btn_ok = QtWidgets.QPushButton("OK")
        self.btn_ok.setVisible(False)
        self.btn_ok.clicked.connect(QtWidgets.QApplication.quit)
        content_layout.addWidget(self.btn_ok, alignment=QtCore.Qt.AlignmentFlag.AlignRight)

        self.error_area = QtWidgets.QPlainTextEdit()
        self.error_area.setReadOnly(True)
        self.error_area.setVisible(False)
        content_layout.addWidget(self.error_area)

        container_layout.addLayout(content_layout)

        # Position at the bottom of the primary screen above taskbar
        self._position_bottom()

        # Auto-close timer for 20s
        self.auto_close_timer = QtCore.QTimer(self)
        self.auto_close_timer.setSingleShot(True)
        self.auto_close_timer.timeout.connect(QtWidgets.QApplication.quit)

        # Start the restart logic in a background thread
        self.worker = RestartWorker(self.pid, self.script_path)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _position_bottom(self):
        screen = QtWidgets.QApplication.primaryScreen()
        if screen:
            geom = screen.availableGeometry()
            x = geom.x() + (geom.width() - self.width()) // 2
            y = geom.y() + geom.height() - self.height() - 20
            self.move(x, y)

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        if event.buttons() == QtCore.Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        self._drag_pos = None

    def _on_finished(self):
        self.status_label.setText("CatchEtude se ha reiniciado con éxito.")
        self.progress_bar.setVisible(False)
        self.btn_ok.setVisible(True)
        self.auto_close_timer.start(20000) # 20 seconds auto-disappear

    def _on_error(self, err_msg):
        self.status_label.setText("Error al reiniciar CatchEtude")
        self.status_label.setStyleSheet("color: #ff6b6b; font-weight: bold;")
        self.progress_bar.setVisible(False)
        self.error_area.setPlainText(err_msg)
        self.error_area.setVisible(True)
        self.setFixedSize(550, 220)
        self.btn_ok.setVisible(True)
        self._position_bottom()
        self.auto_close_timer.start(20000)

class RestartWorker(QtCore.QThread):
    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(str)

    def __init__(self, pid, script_path):
        super().__init__()
        self.pid = pid
        self.script_path = script_path

    def _wait_for_mutex_absent(self, name: str, timeout: float = 15.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            handle = None
            try:
                handle = win32event.OpenMutex(win32event.SYNCHRONIZE, False, name)
                if handle:
                    time.sleep(0.2)
                    continue
            except Exception:
                return True
            finally:
                if handle:
                    try:
                        win32api.CloseHandle(handle)
                    except OSError as e:
                        logging.debug(f"Failed to close handle in restart: {e}")
                    except Exception as e:
                        logging.warning(f"Unexpected error closing handle: {e}")
        return False

    def run(self):
        try:
            # 1) Fuerza el apagado de servicios paralelos
            stop_parallel_services(timeout=10.0)

            # 2) Espera a que la app principal realmente desaparezca
            if not self._wait_for_mutex_absent(config.APP_NAME, 15.0):
                raise TimeoutError("El proceso principal no terminó a tiempo.")

            # 3) Asegura que watchdog y character service ya no estén vivos
            if not wait_for_services_stopped(timeout=15.0):
                raise TimeoutError("Los servicios paralelos no terminaron a tiempo.")

            # 4) Arranque limpio
            python_exe = sys.executable
            if self.script_path.lower().endswith('.pyw'):
                if python_exe.lower().endswith("python.exe"):
                    candidate = Path(python_exe).with_name("pythonw.exe")
                    if candidate.exists():
                        python_exe = str(candidate)

            subprocess.Popen(
                [python_exe, self.script_path],
                creationflags=subprocess.CREATE_NO_WINDOW # 0x00000010 es para mostrar
            )

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
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(config.MYAPPID)
    except OSError as e:
        logging.debug(f"Failed to set AppUserModelID (Windows integration): {e}")
    except Exception as e:
        logging.debug(f"Unexpected error setting AppUserModelID: {e}")

    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(QtGui.QIcon(config.ICON_PATH))
    
    win = RestartWindow(pid_to_wait, path_to_restart)
    win.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
