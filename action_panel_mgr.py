"""
Action panel component for CatchEtude.
Componente del panel de acción para CatchEtude.
"""

import os
import logging
from pathlib import Path
from datetime import datetime
from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileIconProvider
from PyQt6.QtCore import Qt

import config
from localization import LocalizationManager
from ui_utils_mgr import apply_secure_blur, load_stylesheet
from shell_video_thumbnail_pyqt6 import get_shell_thumbnail_pixmap, should_use_shell_thumbnail
from drag_label_widget import DragLabel
from rename_dialog import RenameDialog
from action_toolbar import ActionToolBar

class ActionPanel(QWidget):
    """
    Panel for previewing and applying actions to the current file.
    Panel para previsualizar y aplicar acciones al archivo actual.
    """
    delete_clicked = QtCore.pyqtSignal()
    flat_folder_clicked = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loc = LocalizationManager()
        self.filepath = None
        self._metadata_dialogs = {}
        self.preview_hidden = False
        self._hide_secure = False
        self._preview_generation = 0
        self._preview_loading_suspended = False
        self._build_ui()

    def _build_ui(self):
        self.setMaximumWidth(350)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 0, 0, 0)
        
        self.action_toolbar = ActionToolBar()
        
        self.action_toolbar.open_clicked.connect(self._open_file)
        self.action_toolbar.delete_clicked.connect(self._show_delete_menu)
        self.action_toolbar.flat_folder_clicked.connect(self.flat_folder_clicked.emit)
        self.action_toolbar.edit_metadata_clicked.connect(self._open_metadata_editor)
        
        top_action_panel_row = QHBoxLayout()
        top_action_panel_row.setSpacing(10)
        top_action_panel_row.setContentsMargins(5, 15, 5, 5) 
        top_action_panel_row.addWidget(self.action_toolbar)
        top_action_panel_row.addStretch()
        
        layout.addLayout(top_action_panel_row)
        
        # Preview Section
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(324, 180)
        self.preview_label.setFrameShape(QtWidgets.QFrame.Shape.Box)
        self.preview_label.setScaledContents(False)
        self.preview_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview_label.mousePressEvent = self._toggle_preview
        layout.addWidget(self.preview_label, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        # Contextual plugin actions use their own two-column grid. Keeping
        # them separate from Open/Delete prevents three or more buttons from
        # competing for the narrow width of the action panel.
        self.dynamic_btn_layout = QtWidgets.QGridLayout()
        self.dynamic_btn_layout.setContentsMargins(0, 0, 0, 0)
        self.dynamic_btn_layout.setHorizontalSpacing(8)
        self.dynamic_btn_layout.setVerticalSpacing(6)
        self.dynamic_btn_layout.setColumnStretch(0, 1)
        self.dynamic_btn_layout.setColumnStretch(1, 1)
        layout.addLayout(self.dynamic_btn_layout)

        self.lbl_file_info = QLabel("Waiting for files...")
        self.lbl_file_info.setWordWrap(True)
        self.lbl_file_info.setAlignment(QtCore.Qt.AlignmentFlag.AlignTop | QtCore.Qt.AlignmentFlag.AlignLeft)
        self.lbl_file_info.setStyleSheet(load_stylesheet("action_panel_file_info.css"))
        self.lbl_file_info.setMinimumHeight(80)
        self.lbl_file_info.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.lbl_file_info.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        self.lbl_file_info.setBackgroundRole(QtGui.QPalette.ColorRole.Base)
        self.lbl_file_info.setAutoFillBackground(True)
        
        self.lbl_file_info.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred, 
            QtWidgets.QSizePolicy.Policy.Expanding
        )
        
        info_container = QWidget()
        info_layout = QVBoxLayout(info_container)
        info_layout.setContentsMargins(5, 0, 5, 10)  # (Izquierda, Arriba, Derecha, Abajo)
        info_layout.addWidget(self.lbl_file_info)
        
        layout.addWidget(info_container)

        # Buttons
        footer = QVBoxLayout()
        footer.setSpacing(6)
        layout.addLayout(footer)

    def retranslate_ui(self):
        self.action_toolbar.retranslate_ui()

    def set_file(self, p: Path, hide_secure: bool):
        self._preview_generation += 1
        self._preview_loading_suspended = False
        self.filepath = p
        self._hide_secure = hide_secure
    
        if p.is_dir():
            self._update_folder_info_label()
            self.load_preview()
            self.action_toolbar.set_file(p)
            self.action_toolbar.action_open.setEnabled(True)
            self.action_toolbar.action_flat_folder.setVisible(True)
            self.action_toolbar.action_delete.setEnabled(False)
            self._update_metadata_button_visibility()
            self._update_dynamic_plugin_buttons()
            return

        self.action_toolbar.action_flat_folder.setVisible(False)
        self.action_toolbar.action_open.setEnabled(True)
        self.action_toolbar.action_delete.setEnabled(True)
        self._update_file_info_label()        
        self.load_preview()
        self.action_toolbar.set_file(p)
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
        self.action_toolbar.action_edit_metadata.setVisible(visible)
        self.action_toolbar.action_edit_metadata.setEnabled(visible)

    def _open_metadata_editor(self):
        if not self._is_metadata_editable():
            return

        file_key = str(self.filepath.resolve())

        try:
            dialog = RenameDialog(file_key)
            self._metadata_dialogs[file_key] = dialog
            dialog.destroyed.connect(
                lambda *_args, key=file_key: self._metadata_dialogs.pop(key, None)
            )
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        except Exception:
            self._metadata_dialogs.pop(file_key, None)
            logging.exception("Error opening embedded metadata editor")


    def get_new_name(self):
        pass

    def clear(self):
        self._preview_generation += 1
        self._preview_loading_suspended = True
        self.filepath = None
        self.preview_label.clear()
        self.lbl_file_info.setText(self.loc.get("msg_no_file"))
        self.action_toolbar.set_file(None)
        self.action_toolbar.action_flat_folder.setVisible(False)
        self.action_toolbar.action_delete.setEnabled(False)
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
        is_directory = self.filepath.is_dir()

        visible_buttons = []

        for btn_def in buttons_def:
            btn_target = btn_def.get("target", "file")
            if btn_target == "subfolder":
                continue
            if is_directory and btn_target != "directory":
                continue
            if not is_directory and btn_target == "directory":
                continue

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

            visible_buttons.append(btn)

        # Use at most two buttons per row. A final unpaired button spans the
        # whole row so it remains centered instead of leaving an empty column.
        for index, btn in enumerate(visible_buttons):
            row, column = divmod(index, 2)
            is_unpaired_last = (
                len(visible_buttons) % 2 == 1
                and index == len(visible_buttons) - 1
            )
            if is_unpaired_last:
                self.dynamic_btn_layout.addWidget(
                    btn, row, 0, 1, 2, Qt.AlignmentFlag.AlignCenter
                )
            else:
                self.dynamic_btn_layout.addWidget(
                    btn, row, column, Qt.AlignmentFlag.AlignCenter
                )

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

        widget = self.action_toolbar.widgetForAction(self.action_toolbar.action_delete)
        if widget:
            menu.exec(widget.mapToGlobal(QtCore.QPoint(0, widget.height())))
        else:
            menu.exec(QtGui.QCursor.pos())

