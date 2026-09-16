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
        
        # Controladores de tiempo y estado
        self.mouse_pressed = False
        self.drag_start_position = QtCore.QPoint()
        self.drag_timer = QtCore.QTimer(self)
        self.drag_timer.setSingleShot(True)
        self.drag_timer.timeout.connect(self.start_validated_drag)
                
        # We'll use a standard icon for dragging
        # Using a system icon or a placeholder if ICON_PATH fails
        provider = QFileIconProvider()
        icon = provider.icon(QtWidgets.QFileIconProvider.IconType.File)
        self.setPixmap(icon.pixmap(20, 20))

    def set_file(self, filepath: Path):
        self.filepath = filepath
        provider = QFileIconProvider()
        if filepath:
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            pixmap = provider.icon(QtCore.QFileInfo(str(filepath))).pixmap(24, 24)
            self.setPixmap(pixmap)
            self.setEnabled(True)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
            icon = provider.icon(QtWidgets.QFileIconProvider.IconType.File)
            self.setPixmap(icon.pixmap(20, 20))
            self.setEnabled(False)

    def mousePressEvent(self, event):
        # 1. Cuando se hace click, solo activamos la cuenta regresiva del temporizador
        if event.button() == Qt.MouseButton.LeftButton and self.filepath and self.filepath.exists():
            self.mouse_pressed = True
            self.drag_start_position = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            
            # Forzar el inicio del temporizador a 2000 milisegundos (2 segundos)
            self.drag_timer.start(90)
            
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.mouse_pressed:
            return

        # 2. Si el usuario mueve el mouse significativamente ANTES de los 2 segundos,
        # significa que no mantuvo la presión estática requerida por la regla. Cancelamos.
        manhattan_dist = (event.position().toPoint() - self.drag_start_position).manhattanLength()
        if manhattan_dist > QtWidgets.QApplication.startDragDistance():
            if self.drag_timer.isActive():
                self.drag_timer.stop()
                self.mouse_pressed = False
                self.setCursor(Qt.CursorShape.OpenHandCursor)

        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.mouse_pressed = False
            
            # 3. Si suelta el click antes de que el temporizador termine, se cancela el proceso
            if self.drag_timer.isActive():
                self.drag_timer.stop()
                self.setCursor(Qt.CursorShape.OpenHandCursor)
                
        super().mouseReleaseEvent(event)


    def start_validated_drag(self):
        """
        Se ejecuta tras mantener presionado por 1 segundos. 
        Mueve la ventana fuera de la pantalla en lugar de alterar flags.
        """
        if not self.mouse_pressed or not self.filepath or not self.filepath.exists():
            return

        # 1. Configurar la data de arrastre habitual
        drag = QDrag(self)
        mime_data = QMimeData()
        url = QtCore.QUrl.fromLocalFile(str(self.filepath.absolute()))
        mime_data.setUrls([url])
        drag.setMimeData(mime_data)
        
        pixmap = self.pixmap().scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QtCore.QPoint(pixmap.width() // 2, pixmap.height() // 2))

        # 2. Guardar la posición geométrica original de la ventana principal
        main_win = self.window()
        original_geometry = main_win.geometry()

        try:
            # 3. Teletransportamos la ventana fuera de la vista del usuario.
            # Al usar move(), el handle nativo permanece intacto y el drag NO se cancela.
            main_win.move(-10000, -10000)
            
            # Esto mantiene el hilo esperando hasta que ocurra el drop o se cancele
            drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction)

        finally:
            # 4. En el instante en que el usuario suelta el click, restauramos la ventana al lugar exacto
            self.mouse_pressed = False
            main_win.setGeometry(original_geometry)
            self.setCursor(Qt.CursorShape.OpenHandCursor)