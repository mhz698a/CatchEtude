import os
import logging
import subprocess
from pathlib import Path
from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QFileIconProvider, QSizePolicy, QApplication
from PyQt6.QtCore import Qt, QMimeData, QMimeDatabase
from PyQt6.QtGui import QDrag, QPixmap

from localization import LocalizationManager
from ui_utils_mgr import apply_secure_blur
from shell_video_thumbnail_pyqt6 import get_shell_thumbnail_pixmap, should_use_shell_thumbnail


class DragLabel(QLabel):
    """
    Icon/Label that enables drag and drop of the current file.
    Icono/Etiqueta que permite arrastrar y soltar el archivo actual.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.filepath = None
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Arrastrar archivo / Drag file")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("border: 1px dashed #ccc; border-radius: 4px;")

        provider = QFileIconProvider()
        icon = provider.icon(QtWidgets.QFileIconProvider.IconType.File)
        self.setPixmap(icon.pixmap(20, 20))

        self._drag_timer = QtCore.QTimer(self)
        self._drag_timer.setSingleShot(True)
        self._drag_timer.setInterval(2000)
        self._drag_timer.timeout.connect(self._start_drag)
        self._is_pressed = False

    def set_file(self, filepath: Path):
        self.filepath = filepath
        provider = QFileIconProvider()
        if filepath:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            pixmap = provider.icon(QtCore.QFileInfo(str(filepath))).pixmap(24, 24)
            self.setPixmap(pixmap)
            self.setEnabled(True)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            icon = provider.icon(QtWidgets.QFileIconProvider.IconType.File)
            self.setPixmap(icon.pixmap(20, 20))
            self.setEnabled(False)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.filepath and self.filepath.exists():
            self._is_pressed = True
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._drag_timer.start()

    def mouseReleaseEvent(self, event):
        self._is_pressed = False
        self._drag_timer.stop()
        if self.filepath:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().mouseReleaseEvent(event)

    def _start_drag(self):
        if not self._is_pressed or not (QApplication.mouseButtons() & Qt.MouseButton.LeftButton):
            return

        if not self.filepath or not self.filepath.exists():
            return

        drag = QDrag(self)
        mime_data = QMimeData()

        url = QtCore.QUrl.fromLocalFile(str(self.filepath.absolute()))
        mime_data.setUrls([url])

        drag.setMimeData(mime_data)

        pixmap = self.pixmap().scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QtCore.QPoint(pixmap.width() // 2, pixmap.height() // 2))

        main_win = self.window()
        orig_flags = main_win.windowFlags()

        try:
            main_win.setWindowOpacity(0.35)
            main_win.setWindowFlag(Qt.WindowType.WindowTransparentForInput, True)
            main_win.show()

            drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
        finally:
            self._is_pressed = False
            main_win.setWindowOpacity(1.0)
            main_win.setWindowFlags(orig_flags)
            main_win.show()
            main_win.raise_()
            main_win.activateWindow()
            self.setCursor(Qt.CursorShape.SizeAllCursor)
