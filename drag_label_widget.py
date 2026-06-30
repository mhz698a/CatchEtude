import os
import logging
import subprocess
from pathlib import Path
from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QFileIconProvider, QSizePolicy
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
        
        # We'll use a standard icon for dragging
        # Using a system icon or a placeholder if ICON_PATH fails
        provider = QFileIconProvider()
        icon = provider.icon(QtWidgets.QFileIconProvider.IconType.File)
        self.setPixmap(icon.pixmap(20, 20))

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
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            drag = QDrag(self)
            mime_data = QMimeData()
            
            # Use absolute path with backslashes for Windows
            url = QtCore.QUrl.fromLocalFile(str(self.filepath.absolute()))
            mime_data.setUrls([url])
            
            drag.setMimeData(mime_data)
            
            # Create a drag pixmap
            pixmap = self.pixmap().scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            drag.setPixmap(pixmap)
            drag.setHotSpot(QtCore.QPoint(pixmap.width() // 2, pixmap.height() // 2))
            
            drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)
            self.setCursor(Qt.CursorShape.SizeAllCursor)

#