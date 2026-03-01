"""
Action panel component for CatchEtude.
Componente del panel de acción para CatchEtude.
"""

import os
import logging
from pathlib import Path
from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QFileIconProvider
from PyQt6.QtCore import Qt

from config import BLUR_LEVEL
from localization import LocalizationManager

class ActionPanel(QWidget):
    """
    Panel for previewing and applying actions to the current file.
    Panel para previsualizar y aplicar acciones al archivo actual.
    """
    apply_clicked = QtCore.pyqtSignal()
    apply_custom_clicked = QtCore.pyqtSignal()
    delete_clicked = QtCore.pyqtSignal()
    secure_changed = QtCore.pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loc = LocalizationManager()
        self.filepath = None
        self.preview_hidden = False
        self._hide_secure = False
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Preview Section
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(320, 180)
        self.preview_label.setFrameShape(QtWidgets.QFrame.Shape.Box)
        self.preview_label.setScaledContents(False)
        self.preview_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview_label.mousePressEvent = self._toggle_preview
        layout.addWidget(self.preview_label, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        self.btn_open = QPushButton(self.loc.get("btn_open"))
        self.btn_open.clicked.connect(self._open_file)
        self.btn_open.setFixedHeight(30)
        self.btn_open.setFixedWidth(100)
        layout.addWidget(self.btn_open, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        # Rename Section
        self.lbl_name = QLabel(self.loc.get("lbl_new_name"))
        layout.addWidget(self.lbl_name)
        self.rename_input = QLineEdit()
        layout.addWidget(self.rename_input)
        layout.addStretch()

        # Progress Bar
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # Buttons
        footer = QHBoxLayout()
        self.hide_secure_cb = QCheckBox(self.loc.get("btn_secure"))
        self.hide_secure_cb.stateChanged.connect(self._on_hide_secure_changed)
        footer.addWidget(self.hide_secure_cb)

        self.btn_custom = QPushButton(self.loc.get("btn_apply_custom"))
        self.btn_custom.setFixedHeight(30)
        self.btn_custom.clicked.connect(self.apply_custom_clicked.emit)
        footer.addWidget(self.btn_custom)

        self.btn_move = QPushButton(self.loc.get("btn_apply"))
        self.btn_move.setFixedHeight(30)
        self.btn_move.clicked.connect(self.apply_clicked.emit)
        footer.addWidget(self.btn_move)

        self.btn_custom.setEnabled(False)
        self.btn_move.setEnabled(False)
        layout.addLayout(footer)

    def retranslate_ui(self):
        self.btn_open.setText(self.loc.get("btn_open"))
        self.lbl_name.setText(self.loc.get("lbl_new_name"))
        self.hide_secure_cb.setText(self.loc.get("btn_secure"))
        self.btn_custom.setText(self.loc.get("btn_apply_custom"))
        self.btn_move.setText(self.loc.get("btn_apply"))

    def set_file(self, p: Path, hide_secure: bool):
        self.filepath = p
        self._hide_secure = hide_secure
        self.hide_secure_cb.setChecked(hide_secure)
        self.rename_input.setText(p.stem)
        self.load_preview()
        self.btn_custom.setEnabled(True)
        # Note: btn_move enabling depends on type, handled by MainWindow

    def load_preview(self):
        if not self.filepath: return
        p = self.filepath
        try:
            if p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}:
                reader = QtGui.QImageReader(str(p))
                reader.setAutoTransform(True)
                target = self.preview_label.size()
                img_size = reader.size()
                if img_size.isValid():
                    reader.setScaledSize(img_size.scaled(target, Qt.AspectRatioMode.KeepAspectRatio))
                img = reader.read()
                if not img.isNull():
                    if self._hide_secure:
                        img = self._apply_secure_blur(img)
                    self.preview_label.setPixmap(QtGui.QPixmap.fromImage(img))
                    return

            provider = QFileIconProvider()
            pixmap = provider.icon(QtCore.QFileInfo(str(p))).pixmap(64, 64)
            if self._hide_secure:
                img = pixmap.toImage()
                img = self._apply_secure_blur(img)
                pixmap = QtGui.QPixmap.fromImage(img)
            self.preview_label.setPixmap(pixmap)
        except Exception:
            logging.exception("Error loading preview")

    def _apply_secure_blur(self, image: QtGui.QImage) -> QtGui.QImage:
        if image.isNull(): return image
        blur_radius = BLUR_LEVEL
        small = image.scaled(image.width() // blur_radius, image.height() // blur_radius,
                             Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        blurred = small.scaled(image.width(), image.height(),
                               Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        result = QtGui.QImage(image.size(), QtGui.QImage.Format.Format_ARGB32)
        result.fill(Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(result)
        reveal_height = int(image.height() * 0.15)
        blur_height = image.height() - reveal_height
        painter.drawImage(QtCore.QRect(0, 0, image.width(), blur_height), blurred, QtCore.QRect(0, 0, image.width(), blur_height))
        painter.drawImage(QtCore.QRect(0, blur_height, image.width(), reveal_height), image, QtCore.QRect(0, blur_height, image.width(), reveal_height))
        painter.end()
        return result

    def _toggle_preview(self, event):
        if not self.filepath: return
        self.preview_hidden = not self.preview_hidden
        if self.preview_hidden:
            self.preview_label.clear()
            self.preview_label.setPixmap(QFileIconProvider().icon(QtCore.QFileInfo(str(self.filepath))).pixmap(32, 32))
        else:
            self.load_preview()

    def _open_file(self):
        if self.filepath:
            os.startfile(str(self.filepath))

    def _on_hide_secure_changed(self, state):
        self._hide_secure = (state == Qt.CheckState.Checked.value)
        self.secure_changed.emit(self._hide_secure)
        self.load_preview()

    def set_progress(self, val):
        self.progress.setValue(val)

    def get_new_name(self):
        return self.rename_input.text().strip()

    def set_apply_enabled(self, enabled):
        self.btn_move.setEnabled(enabled)

    def clear(self):
        self.filepath = None
        self.preview_label.clear()
        self.rename_input.setText("")
        self.progress.setValue(0)
