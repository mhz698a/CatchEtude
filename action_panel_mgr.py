"""
Action panel component for CatchEtude.
Componente del panel de acción para CatchEtude.
"""

import os
import logging
import subprocess
from pathlib import Path
from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QFileIconProvider, QSizePolicy
from PyQt6.QtCore import Qt, QMimeData, QMimeDatabase
from PyQt6.QtGui import QDrag, QPixmap

from config import BLUR_LEVEL, ICON_PATH, METADATA_EDIT_SCRIPT_PATH, METADATA_EDIT_EXTS
from localization import LocalizationManager
from ui_utils_mgr import apply_secure_blur
from shell_video_thumbnail_pyqt6 import get_shell_thumbnail_pixmap, should_use_shell_thumbnail
from drag_label_widget import DragLabel

class ActionPanel(QWidget):
    """
    Panel for previewing and applying actions to the current file.
    Panel para previsualizar y aplicar acciones al archivo actual.
    """
    apply_clicked = QtCore.pyqtSignal()
    apply_custom_clicked = QtCore.pyqtSignal()
    delete_clicked = QtCore.pyqtSignal()
    secure_changed = QtCore.pyqtSignal(bool)
    keep_changed = QtCore.pyqtSignal(bool)
    post_action_changed = QtCore.pyqtSignal(str)
    hide_t_clicked = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loc = LocalizationManager()
        self.filepath = None
        self.preview_hidden = False
        self._hide_secure = False
        self._build_ui()

    def _build_ui(self):
        self.setMaximumWidth(350)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 0, 0, 0)
        
        # Preview Section
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(320, 180)
        self.preview_label.setFrameShape(QtWidgets.QFrame.Shape.Box)
        self.preview_label.setScaledContents(False)
        self.preview_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview_label.mousePressEvent = self._toggle_preview
        layout.addWidget(self.preview_label, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        open_row = QHBoxLayout()
        open_row.setSpacing(8)
        open_row.addStretch()

        self.btn_open = QPushButton(self.loc.get("btn_open"))
        self.btn_open.clicked.connect(self._open_file)
        self.btn_open.setFixedHeight(30)
        self.btn_open.setFixedWidth(100)
        open_row.addWidget(self.btn_open)

        self.btn_edit_metadata = QPushButton("Edit metadata")
        self.btn_edit_metadata.clicked.connect(self._open_metadata_editor)
        self.btn_edit_metadata.setFixedHeight(30)
        self.btn_edit_metadata.setFixedWidth(110)
        self.btn_edit_metadata.setVisible(False)
        open_row.addWidget(self.btn_edit_metadata)

        open_row.addStretch()
        layout.addLayout(open_row)

        # Rename Section
        self.lbl_name = QLabel(self.loc.get("lbl_new_name"))
        layout.addWidget(self.lbl_name)
        self.rename_input = QLineEdit()
        layout.addWidget(self.rename_input)
        
        self.lbl_file_info = QLabel("")
        self.lbl_file_info.setStyleSheet("font-style: italic; font-size: 11px; margin-left: 5px;")
        layout.addWidget(self.lbl_file_info)
        
        layout.addStretch()        

        # Progress Bar
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # Buttons
        footer = QVBoxLayout()
        footer.setSpacing(6)                        
                                
        top_row = QHBoxLayout()
        top_row.setSpacing(10)     
                
        self.drag_icon = DragLabel()
        self.drag_icon.setEnabled(False)
        top_row.addWidget(self.drag_icon)
        
        self.hide_secure_cb = QCheckBox(self.loc.get("btn_secure"))
        self.hide_secure_cb.stateChanged.connect(self._on_hide_secure_changed)
        top_row.addWidget(self.hide_secure_cb)
        
        self.keep_downloads_cb = QCheckBox(self.loc.get("keep in downloads"))
        self.keep_downloads_cb.toggled.connect(self._on_keep_downloads_changed)
        top_row.addWidget(self.keep_downloads_cb)
        top_row.addStretch()
        
        # comobox action after download
        self.lbl_post_action = QLabel(self.loc.get("lbl_post_action"))

        self.post_action_row = QHBoxLayout()
        self.post_action_row.addWidget(self.lbl_post_action)

        self.post_action_cb = QComboBox()
        self.post_action_cb.setMaximumWidth(310)
        self.post_action_cb.addItem(self.loc.get("post_action_none"), "none")
        self.post_action_cb.addItem(self.loc.get("post_action_open_file"), "open_file")
        self.post_action_cb.addItem(self.loc.get("post_action_open_folder"), "open_folder")
        self.post_action_cb.currentIndexChanged.connect(
            lambda _: self.post_action_changed.emit(self.get_post_action_mode())
        )

        self.post_action_row.addWidget(self.post_action_cb)
        self.post_action_row.addStretch(1)

        footer.addLayout(top_row)
        footer.addLayout(self.post_action_row)
    
        # buttons arrow
        buttons_row = QHBoxLayout()
        buttons_row.setContentsMargins(0, 0, 0, 0)
        buttons_row.setSpacing(8)

        self.btn_hide_t = QPushButton("Hide Temporal")
        self.btn_hide_t.setMinimumHeight(30)
        self.btn_hide_t.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_hide_t.clicked.connect(self.hide_t_clicked.emit)
        buttons_row.addWidget(self.btn_hide_t, 1)

        self.btn_custom = QPushButton(self.loc.get("btn_apply_custom"))
        self.btn_custom.setMinimumHeight(30)
        self.btn_custom.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_custom.clicked.connect(self.apply_custom_clicked.emit)
        buttons_row.addWidget(self.btn_custom, 1)

        self.btn_move = QPushButton(self.loc.get("btn_apply"))
        self.btn_move.setMinimumHeight(30)
        self.btn_move.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_move.clicked.connect(self.apply_clicked.emit)
        buttons_row.addWidget(self.btn_move, 1)

        footer.addLayout(buttons_row)

        self.btn_custom.setEnabled(False)
        self.btn_move.setEnabled(False)
        layout.addLayout(footer)

    def retranslate_ui(self):
        self.lbl_post_action.setText(self.loc.get("lbl_post_action"))
        self.btn_edit_metadata.setText("Edit metadata")
        
        current = self.get_post_action_mode()
        self.post_action_cb.blockSignals(True)
        self.post_action_cb.setItemText(0, self.loc.get("post_action_none"))
        self.post_action_cb.setItemText(1, self.loc.get("post_action_open_file"))
        self.post_action_cb.setItemText(2, self.loc.get("post_action_open_folder"))
        self.set_post_action_mode(current)
        self.post_action_cb.blockSignals(False)

        self.btn_open.setText(self.loc.get("btn_open"))
        self.lbl_name.setText(self.loc.get("lbl_new_name"))
        self.hide_secure_cb.setText(self.loc.get("btn_secure"))
        self.keep_downloads_cb.setText(self.loc.get("keep_in_downloads"))
        self.btn_hide_t.setText("Hide Temporal")
        self.btn_custom.setText(self.loc.get("btn_apply_custom"))
        self.btn_move.setText(
            self.loc.get("btn_keep") if self.keep_downloads_cb.isChecked() else self.loc.get("btn_apply")
        )

    def set_file(self, p: Path, hide_secure: bool):
        self.filepath = p
        self._hide_secure = hide_secure
        self.hide_secure_cb.setChecked(hide_secure)
        self.rename_input.setText(p.stem)
        self._update_file_info_label()        
        self.load_preview()
        self.drag_icon.set_file(p)
        self.btn_custom.setEnabled(True)
        self.btn_hide_t.setEnabled(True)
        self._update_metadata_button_visibility()
        # Note: btn_move enabling depends on type, handled by MainWindow

    def _update_file_info_label(self):
        if not self.filepath:
            self.lbl_file_info.setText("")
            return

        p = self.filepath
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg"}

        if p.suffix.lower() in image_exts:
            try:
                reader = QtGui.QImageReader(str(p))
                size = reader.size()
                if size.isValid():
                    self.lbl_file_info.setText(
                        f"Tipo: Imagen ({size.width()} x {size.height()})"
                    )
                else:
                    self.lbl_file_info.setText("Tipo: Imagen")
            except Exception:
                self.lbl_file_info.setText("Tipo: Imagen")
            return

        mime = QtCore.QMimeDatabase().mimeTypeForFile(str(p)).name()
        group = mime.split("/", 1)[0] if "/" in mime else ""

        type_map = {
            "audio": "Audio",
            "video": "Video",
            "image": "Imagen",
            "text": "Texto",
            "application": "Aplicación",
        }

        self.lbl_file_info.setText(f"Tipo: {type_map.get(group, 'Archivo')}")

    def load_preview(self):
        if not self.filepath: return
        p = self.filepath
        try:
            
            ext = p.suffix.lower()
            target = self.preview_label.size()

            if should_use_shell_thumbnail(ext):
                shell_pixmap = get_shell_thumbnail_pixmap(str(p), max(target.width(), target.height()))
                if shell_pixmap and not shell_pixmap.isNull():
                    if self._hide_secure:
                        img = apply_secure_blur(shell_pixmap.toImage())
                        shell_pixmap = QtGui.QPixmap.fromImage(img)

                    self.preview_label.setPixmap(
                        shell_pixmap.scaled(
                            target,
                            Qt.AspectRatioMode.KeepAspectRatio,
                            Qt.TransformationMode.SmoothTransformation,
                        )
                    )
                    return

            if ext in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}:
                reader = QtGui.QImageReader(str(p))
                reader.setAutoTransform(True)
                img_size = reader.size()
                if img_size.isValid():
                    reader.setScaledSize(img_size.scaled(target, Qt.AspectRatioMode.KeepAspectRatio))
                img = reader.read()
                if not img.isNull():
                    if self._hide_secure:
                        img = apply_secure_blur(img)
                    self.preview_label.setPixmap(QtGui.QPixmap.fromImage(img))
                    return

            provider = QFileIconProvider()
            pixmap = provider.icon(QtCore.QFileInfo(str(p))).pixmap(64, 64)
            if self._hide_secure:
                img = pixmap.toImage()
                img = apply_secure_blur(img)
                pixmap = QtGui.QPixmap.fromImage(img)
            self.preview_label.setPixmap(pixmap)
            
        except Exception:
            logging.exception("Error loading preview")

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

    def _is_metadata_editable(self) -> bool:
        return bool(self.filepath) and self.filepath.suffix.lower() in METADATA_EDIT_EXTS

    def _update_metadata_button_visibility(self):
        visible = self._is_metadata_editable()
        self.btn_edit_metadata.setVisible(visible)
        self.btn_edit_metadata.setEnabled(visible)

    def _open_metadata_editor(self):
        if not self._is_metadata_editable():
            return

        try:
            subprocess.Popen(
                ["pythonw", str(METADATA_EDIT_SCRIPT_PATH), str(self.filepath)],
                close_fds=True,
            )
        except Exception:
            logging.exception("Error launching metadata editor")

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
        self.lbl_file_info.setText("")
        self.progress.setValue(0)
        self.drag_icon.set_file(None)
        self.btn_hide_t.setEnabled(False)
        self._update_metadata_button_visibility()

    def _on_keep_downloads_changed(self, checked: bool):
        self.btn_move.setText(self.loc.get("btn_keep") if checked else self.loc.get("btn_apply"))
        self.keep_changed.emit(checked)

    def is_keep_downloads(self) -> bool:
        return self.keep_downloads_cb.isChecked()

    def get_post_action_mode(self) -> str:
        data = self.post_action_cb.currentData()
        return data if data in ("none", "open_file", "open_folder") else "none"

    def set_post_action_mode(self, mode: str):
        idx = self.post_action_cb.findData(mode)
        if idx < 0:
            idx = self.post_action_cb.findData("none")
        if idx >= 0:
            self.post_action_cb.setCurrentIndex(idx)