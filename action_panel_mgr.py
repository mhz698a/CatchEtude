"""
Action panel component for CatchEtude.
Componente del panel de acción para CatchEtude.
"""

import os
import logging
import subprocess
from pathlib import Path
from datetime import datetime
from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QCheckBox, QComboBox, QFileIconProvider, QSizePolicy, QSpinBox
from PyQt6.QtCore import Qt, QMimeData, QMimeDatabase
from PyQt6.QtGui import QDrag, QPixmap
import config
from localization import LocalizationManager
from ui_utils_mgr import apply_secure_blur
from shell_video_thumbnail_pyqt6 import get_shell_thumbnail_pixmap, should_use_shell_thumbnail
from drag_label_widget import DragLabel

class ActionPanel(QWidget):
    """
    Panel for previewing and applying actions to the current file.
    Panel para previsualizar y aplicar acciones al archivo actual.
    """
    delete_clicked = QtCore.pyqtSignal()
    hide_t_clicked = QtCore.pyqtSignal()
    flat_folder_clicked = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loc = LocalizationManager()
        self.filepath = None
        self.preview_hidden = False
        self._hide_secure = False
        self._preview_generation = 0
        self._preview_loading_suspended = False
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

        self.dynamic_btn_layout = QHBoxLayout()
        self.dynamic_btn_layout.setSpacing(8)
        open_row.addLayout(self.dynamic_btn_layout)

        self.btn_open = QPushButton(self.loc.get("btn_open"))
        self.btn_open.clicked.connect(self._open_file)
        self.btn_open.setFixedHeight(30)
        self.btn_open.setFixedWidth(90)
        open_row.addWidget(self.btn_open)

        self.btn_delete = QPushButton(self.loc.get("btn_header_delete"))
        self.btn_delete.clicked.connect(self._show_delete_menu)
        self.btn_delete.setFixedHeight(30)
        self.btn_delete.setFixedWidth(100)
        self.btn_delete.setEnabled(False)
        open_row.addWidget(self.btn_delete)

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
        self.lbl_file_info.setWordWrap(True)
        self.lbl_file_info.setStyleSheet("font-style: italic; font-size: 11px; margin-left: 5px;")
        self.lbl_file_info.setMinimumHeight(80)
        layout.addWidget(self.lbl_file_info)
        
        layout.addStretch()        

        # Buttons
        footer = QVBoxLayout()
        footer.setSpacing(6)                        
                                
        # Drag row
        drag_row = QHBoxLayout()
        drag_row.setSpacing(10)
                
        self.drag_icon = DragLabel()
        self.drag_icon.setEnabled(False)
        drag_row.addWidget(self.drag_icon)
        drag_row.addStretch()

        footer.addLayout(drag_row)
    
        # buttons arrow
        buttons_row = QHBoxLayout()
        buttons_row.setContentsMargins(0, 0, 0, 0)
        buttons_row.setSpacing(8)

        self.btn_hide_t = QPushButton("Hide Temporal")
        self.btn_hide_t.setMinimumHeight(30)
        self.btn_hide_t.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_hide_t.clicked.connect(self.hide_t_clicked.emit)
        buttons_row.addWidget(self.btn_hide_t, 1)

        self.btn_flat_folder = QPushButton("Flat Folder")
        self.btn_flat_folder.setMinimumHeight(30)
        self.btn_flat_folder.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_flat_folder.setEnabled(True)
        self.btn_flat_folder.clicked.connect(self.flat_folder_clicked.emit)
        buttons_row.addWidget(self.btn_flat_folder, 1)

        footer.addLayout(buttons_row)
        layout.addLayout(footer)

    def retranslate_ui(self):
        self.btn_edit_metadata.setText("Edit metadata")
        self.btn_open.setText(self.loc.get("btn_open"))
        self.btn_delete.setText(self.loc.get("btn_header_delete"))
        self.lbl_name.setText(self.loc.get("lbl_new_name"))
        self.btn_hide_t.setText("Hide Temporal")
        self.btn_flat_folder.setText("Flat Folder")

    def set_file(self, p: Path, hide_secure: bool):
        self._preview_generation += 1
        self._preview_loading_suspended = False
        self.filepath = p
        self._hide_secure = hide_secure
        self.rename_input.setText(p.stem)

        if p.is_dir():
            self._update_folder_info_label()
            self.load_preview()
            self.drag_icon.set_file(p)
            self.rename_input.setEnabled(False)
            self.btn_open.setEnabled(True)
            self.btn_delete.setEnabled(False)
            self.btn_hide_t.setEnabled(True)
            self._update_metadata_button_visibility()
            self._update_dynamic_plugin_buttons()
            return

        self.rename_input.setEnabled(True)
        self.btn_open.setEnabled(True)
        self.btn_delete.setEnabled(True)
        self._update_file_info_label()        
        self.load_preview()
        self.drag_icon.set_file(p)
        self.btn_hide_t.setEnabled(True)
        self._update_metadata_button_visibility()
        self._update_dynamic_plugin_buttons()

    def _update_folder_info_label(self):
        if not self.filepath:
            self.lbl_file_info.setText("")
            return

        p = self.filepath

        try:
            created = datetime.fromtimestamp(p.stat().st_ctime)
            created_text = created.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            created_text = "-"

        try:
            modified = datetime.fromtimestamp(p.stat().st_mtime)
            modified_text = modified.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            modified_text = "-"

        try:
            item_count = len(list(p.iterdir()))
            count_text = f"{item_count} elementos"
        except Exception:
            count_text = "-"

        self.lbl_file_info.setText(
            "\n".join([
                "Tipo: Carpeta",
                f"Contenido: {count_text}",
                f"Creación: {created_text}",
                f"Modificación: {modified_text}",
            ])
        )

    def _update_file_info_label(self):

        if not self.filepath:
            self.lbl_file_info.setText("")
            return

        p = self.filepath

        folder_name = p.parent.name

        try:
            created = datetime.fromtimestamp(p.stat().st_ctime)
            created_text = created.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            created_text = "-"

        try:
            modified = datetime.fromtimestamp(p.stat().st_mtime)
            modified_text = modified.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            modified_text = "-"

        image_exts = {
            ".png", ".jpg", ".jpeg",
            ".webp", ".gif", ".bmp",
            ".tif", ".tiff", ".svg"
        }

        file_type = "Archivo"

        if p.suffix.lower() in image_exts:
            try:
                reader = QtGui.QImageReader(str(p))
                size = reader.size()

                if size.isValid():
                    file_type = (
                        f"Imagen ({size.width()} x {size.height()})"
                    )
                else:
                    file_type = "Imagen"

            except Exception:
                file_type = "Imagen"

        else:
            mime = QtCore.QMimeDatabase().mimeTypeForFile(str(p)).name()

            group = mime.split("/", 1)[0] if "/" in mime else ""

            type_map = {
                "audio": "Audio",
                "video": "Video",
                "image": "Imagen",
                "text": "Texto",
                "application": "Aplicación",
            }

            file_type = type_map.get(group, "Archivo")

        self.lbl_file_info.setText(
            "\n".join([
                f"Tipo: {file_type}",
                f"Carpeta: {folder_name}",
                f"Creación: {created_text}",
                f"Modificación: {modified_text}",
            ])
        )

    def suspend_preview_loading(self, p: Path | None = None):
        """Stops any pending preview result from being applied to the UI."""
        if p is None or p == self.filepath:
            self._preview_generation += 1
            self._preview_loading_suspended = True
            self.preview_label.clear()

    def _preview_request_is_current(self, p: Path, generation: int) -> bool:
        return (
            not self._preview_loading_suspended
            and generation == self._preview_generation
            and self.filepath == p
            and p.exists()
        )

    def load_preview(self):
        if not self.filepath or self._preview_loading_suspended:
            return
        p = self.filepath
        generation = self._preview_generation
        try:
            if not p.exists():
                return

            ext = p.suffix.lower()
            target = self.preview_label.size()

            if should_use_shell_thumbnail(ext):
                shell_pixmap = get_shell_thumbnail_pixmap(str(p), max(target.width(), target.height()))
                if not self._preview_request_is_current(p, generation):
                    return
                if shell_pixmap and not shell_pixmap.isNull():
                    if self._hide_secure:
                        img = apply_secure_blur(shell_pixmap.toImage())
                        shell_pixmap = QtGui.QPixmap.fromImage(img)

                    if not self._preview_request_is_current(p, generation):
                        return
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
                if not self._preview_request_is_current(p, generation):
                    return
                if not img.isNull():
                    if self._hide_secure:
                        img = apply_secure_blur(img)
                    if not self._preview_request_is_current(p, generation):
                        return
                    self.preview_label.setPixmap(QtGui.QPixmap.fromImage(img))
                    return

            if not self._preview_request_is_current(p, generation):
                return

            if p.is_dir():
                provider = QFileIconProvider()
                pixmap = provider.icon(QFileIconProvider.IconType.Folder).pixmap(64, 64)
                if self._hide_secure:
                    img = pixmap.toImage()
                    img = apply_secure_blur(img)
                    pixmap = QtGui.QPixmap.fromImage(img)
                if self._preview_request_is_current(p, generation):
                    self.preview_label.setPixmap(pixmap)
                return

            provider = QFileIconProvider()
            pixmap = provider.icon(QtCore.QFileInfo(str(p))).pixmap(64, 64)
            if self._hide_secure:
                img = pixmap.toImage()
                img = apply_secure_blur(img)
                pixmap = QtGui.QPixmap.fromImage(img)
            if self._preview_request_is_current(p, generation):
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
        return bool(self.filepath) and self.filepath.suffix.lower() in config.METADATA_EDIT_EXTS

    def _update_metadata_button_visibility(self):
        visible = self._is_metadata_editable()
        self.btn_edit_metadata.setVisible(visible)
        self.btn_edit_metadata.setEnabled(visible)

    def _open_metadata_editor(self):
        if not self._is_metadata_editable():
            return

        try:
            subprocess.Popen(
                ["pythonw", str(config.METADATA_EDIT_SCRIPT_PATH), str(self.filepath)],
                close_fds=True,
            )
        except Exception:
            logging.exception("Error launching metadata editor")


    def get_new_name(self):
        return self.rename_input.text().strip()

    def clear(self):
        self._preview_generation += 1
        self._preview_loading_suspended = True
        self.filepath = None
        self.preview_label.clear()
        self.rename_input.setText("")
        self.rename_input.setEnabled(True)
        self.lbl_file_info.setText(self.loc.get("msg_no_file"))
        self.drag_icon.set_file(None)
        self.btn_hide_t.setEnabled(False)
        self.btn_delete.setEnabled(False)
        self._update_metadata_button_visibility()
        self._update_dynamic_plugin_buttons()

    def _update_dynamic_plugin_buttons(self):
        import sys
        # Clear previous dynamic buttons
        while self.dynamic_btn_layout.count():
            item = self.dynamic_btn_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self.filepath:
            return

        plugin_mgr = getattr(sys.modules.get("__main__"), "plugin_mgr", None)
        if not plugin_mgr:
            return

        buttons_def = plugin_mgr.get_ui_action_buttons()
        ext = self.filepath.suffix.lower()

        for btn_def in buttons_def:
            exts = btn_def.get("file_extensions")
            if exts and ext not in [e.lower() for e in exts]:
                continue

            btn = QPushButton(btn_def.get("label", "Action"))
            btn.setFixedHeight(30)
            btn.setFixedWidth(110)

            plugin_id = btn_def["plugin_id"]
            menu_items = btn_def.get("menu_items")
            command = btn_def.get("command")

            if menu_items:
                btn.clicked.connect(lambda checked, b=btn, pid=plugin_id, items=menu_items: self._show_dynamic_button_menu(b, pid, items))
            elif command:
                btn.clicked.connect(
                    lambda checked, pid=plugin_id, cmd=command: self._invoke_plugin_command(
                        plugin_mgr, pid, cmd
                    )
                )

            self.dynamic_btn_layout.addWidget(btn)

    def _show_dynamic_button_menu(self, button, plugin_id: str, items: list):
        import sys
        plugin_mgr = getattr(sys.modules.get("__main__"), "plugin_mgr", None)
        if not plugin_mgr:
            return

        menu = QtWidgets.QMenu(self)
        for item in items:
            act = QtGui.QAction(item.get("label", "Item"), self)
            cmd = item.get("command", "")
            act.triggered.connect(
                lambda checked, pid=plugin_id, c=cmd: self._invoke_plugin_command(
                    plugin_mgr, pid, c
                )
            )
            menu.addAction(act)

        menu.exec(button.mapToGlobal(QtCore.QPoint(0, button.height())))

    def _invoke_plugin_command(self, plugin_mgr, plugin_id: str, command: str):
        """Invoke a contextual plugin action with the selected queue file.

        UI action buttons are shown for a concrete file, so the host must pass that
        file to the plugin.  Without this context, plugins can only fall back to
        showing their own file picker, which defeats the purpose of the button.
        """
        if not self.filepath:
            return
        plugin_mgr.invoke_command(plugin_id, command, {"paths": [str(self.filepath)]})

    def _show_delete_menu(self):
        if not self.filepath:
            return

        menu = QtWidgets.QMenu(self)

        title_action = QtGui.QAction("¿Eliminar archivo?", self)
        title_action.setEnabled(False)
        menu.addAction(title_action)
        menu.addSeparator()

        act_yes = QtGui.QAction("Sí", self)
        act_yes.triggered.connect(self.delete_clicked.emit)
        menu.addAction(act_yes)

        act_no = QtGui.QAction("No", self)
        menu.addAction(act_no)

        menu.exec(self.btn_delete.mapToGlobal(QtCore.QPoint(0, self.btn_delete.height())))

