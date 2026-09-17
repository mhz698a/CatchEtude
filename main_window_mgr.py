"""
Main Window manager for CatchEtude.
Gestor de la ventana principal para CatchEtude.
"""

import os
import sys
import logging
import json
import threading
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QFileDialog,
    QHBoxLayout, QVBoxLayout, QSystemTrayIcon, QMenu, 
    QMessageBox, QStatusBar, QCheckBox, QTimeEdit, QSpinBox
)
from pending_scheduler_mgr import PendingScheduler
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import Qt, QTime

import config
from utils import (
    resolve_duplicate, 
    configure_dwm_thumbnail_behavior, is_internal_available,
    sanitize_windows_filename, is_temporary,
    is_file_locked, delete_to_recycle_bin, run_in_threadpool,
    flatten_single_folder
)
from state_manager import StateManager, State, scan_existing_downloads
from ui_utils_mgr import load_stylesheet
from fallback_utils import compute_destination
from file_worker_mgr import FileMoveWorker
from app_signals_mgr import AppSignals
from localization import LocalizationManager

from selection_panel_mgr import SelectionPanel
from action_panel_mgr import ActionPanel
from queue_panel_mgr import QueuePanel
from service_mgr import send_character_service_command
from pending_dialog import PendingDialog
from temporary_hide_banner_mgr import TemporaryHideBanner
from background_move_mgr import BackgroundMoveManager
from tray_menu_mgr import TrayMenuManager


class MainWindow(QWidget):
    """
    Main UI window for CatchEtude.
    Ventana principal de la interfaz de CatchEtude.
    """
    def __init__(self, state_manager: StateManager, signals: AppSignals):
        super().__init__()
        self.state_manager = state_manager
        self.signals = signals
        self.loc = LocalizationManager()
        
        self.background_move_mgr = BackgroundMoveManager(self.state_manager, self)
        self.background_move_mgr.move_started.connect(self._on_background_move_started)
        self.background_move_mgr.move_progress.connect(self._on_background_move_progress)
        self.background_move_mgr.move_finished.connect(self._on_background_move_finished)
        self._closing = False
        
        self.signals.file_detected.connect(self.on_file_detected)
        self.signals.queue_empty.connect(self._hide_if_idle)
        self.signals.queue_updated.connect(self._on_queue_updated)
        self.signals.warning_message.connect(self.show_status)
        self.signals.post_action_ready.connect(self._queue_or_run_post_action)
        
        self.setWindowTitle(config.APP_NAME)
        
        flags = QtCore.Qt.WindowType.WindowTitleHint | QtCore.Qt.WindowType.CustomizeWindowHint
        flags |= QtCore.Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
        
        self.base_width = 860
        self.base_height = 580
        self.setMinimumSize(self.base_width, self.base_height)
        
        self._internal_warned = False
        self.filepath: Optional[Path] = None
        self._bulk_subfolder_name: Optional[str] = None
        
        self._hide_secure = False
        self._post_action_mode = "none"
        self._pending_post_actions = {}
        self._post_action_consumed = False
        self._load_config()       
        self._setup_server()
        
        self._build_ui()
        self._pending_dialog = PendingDialog(self.loc, self._bring_and_center)
        self.tray_mgr = TrayMenuManager(self)
        self.tray_mgr.build_tray()
        
        self._hide_t_active = False
        self._hide_t_banner = TemporaryHideBanner(self)
        self._hide_t_banner.show_again_clicked.connect(self._restore_from_hide_t)
        self._hide_t_banner.timeout_reached.connect(self._restore_from_hide_t)
        
        configure_dwm_thumbnail_behavior(self.winId().__int__())
        
        self._year_load_timer = QtCore.QTimer(self)
        self._year_load_timer.setSingleShot(True)
        self._year_load_timer.timeout.connect(self._load_characters_for_year)
        self._pending_year = None
        self._char_load_generation = 0
        
        self._pending_scheduler = None
        
        self._setup_settings_watcher()

    def _setup_settings_watcher(self):
        self._settings_watcher = QtCore.QFileSystemWatcher([str(config.SETTINGS_PATH)], self)
        self._settings_watcher.fileChanged.connect(self._on_settings_file_changed)

    def _on_settings_file_changed(self, path):
        logging.info(f"Settings file changed: {path}. Reloading...")
        config.apply_settings()
        
        # QFileSystemWatcher might lose the file after it's overwritten by some editors
        if str(config.SETTINGS_PATH) not in self._settings_watcher.files():
            self._settings_watcher.addPath(str(config.SETTINGS_PATH))

        self.retranslate_ui()
        # Some changes might require more specific updates
        self.selection_panel.refresh_classification_ui(force=True)

    def _build_ui(self):
        main_vbox = QVBoxLayout(self)
        
        # Header Row
        header_layout = QHBoxLayout()
        
        self.btn_reload = QPushButton(self.loc.get("btn_reload"))
        self.btn_reload.setFixedHeight(25)
        self.btn_reload.setToolTip(self.loc.get("tooltip_reload"))
        self.btn_reload.clicked.connect(self._on_reload_clicked)

        self.hide_secure_cb = QCheckBox(self.loc.get("btn_secure"))
        self.hide_secure_cb.setFixedHeight(25)
        self.hide_secure_cb.setChecked(self._hide_secure)
        self.hide_secure_cb.stateChanged.connect(self._on_secure_changed)

        self.blur_spinbox = QSpinBox()
        self.blur_spinbox.setFixedHeight(25)
        self.blur_spinbox.setRange(1, 255)
        self.blur_spinbox.setValue(config.BLUR_LEVEL)
        self.blur_spinbox.setToolTip("Nivel de difuminado (1-255)")
        self.blur_spinbox.valueChanged.connect(self._on_blur_level_changed)

        self.chk_auto_run_pendings = QCheckBox()
        self.chk_auto_run_pendings.setFixedHeight(25)
        self.chk_auto_run_pendings.toggled.connect(self._on_pending_schedule_changed)

        self.time_auto_run_pendings = QTimeEdit()
        self.time_auto_run_pendings.setDisplayFormat("HH:mm")
        self.time_auto_run_pendings.setFixedHeight(25)
        self.time_auto_run_pendings.setFixedWidth(80)
        self.time_auto_run_pendings.timeChanged.connect(self._on_pending_schedule_changed)

        self.btn_hide = QPushButton(self.loc.get("btn_hide"))
        self.btn_hide.setFixedHeight(25)
        self.btn_hide.clicked.connect(self._manual_hide)

        self.btn_undo = QPushButton(self.loc.get("btn_history"))
        self.btn_undo.setFixedHeight(25)
        self.btn_undo.clicked.connect(self._on_undo_clicked)
        
        self.btn_lang = QPushButton(self.loc.get("lang_toggle"))
        self.btn_lang.setFixedWidth(40)
        self.btn_lang.setFixedHeight(25)
        self.btn_lang.clicked.connect(self._on_lang_toggle)
        
        header_layout.addWidget(self.btn_reload)
        header_layout.addStretch()
        header_layout.addWidget(self.hide_secure_cb)
        header_layout.addWidget(self.blur_spinbox)
        header_layout.addWidget(self.chk_auto_run_pendings)
        header_layout.addWidget(self.time_auto_run_pendings)
        header_layout.addWidget(self.btn_hide)
        header_layout.addWidget(self.btn_undo)
        header_layout.addWidget(self.btn_lang)
        main_vbox.addLayout(header_layout)

        # CENTRO
        root = QHBoxLayout()
        
        # Selection Panel
        self.selection_panel = SelectionPanel()
        self.selection_panel.subfolder_clicked.connect(self._move_to_subfolder)
        self.selection_panel.undo_clicked.connect(self._on_context_undo_clicked)
        self.selection_panel.move_and_open_file_clicked.connect(lambda sub: self._move_to_subfolder(sub, post_action="open_file"))
        self.selection_panel.move_and_open_folder_clicked.connect(lambda sub: self._move_to_subfolder(sub, post_action="open_folder"))
        self.selection_panel.move_all_and_open_folder_clicked.connect(lambda sub: self._move_all_in_this_folder(sub, post_action="open_folder"))
        self.selection_panel.hide_temporal_clicked.connect(self._on_hide_t_clicked)
        self.selection_panel.move_and_enable_secure_clicked.connect(self._move_and_enable_secure)
        self.selection_panel.keep_action_clicked.connect(self._on_keep_action_clicked)
        self.selection_panel.linear_docs_action_clicked.connect(self._on_linear_docs_action_clicked)
        self.selection_panel.subfolders_refreshed.connect(self._update_character_buttons)
        self.selection_panel.move_all_in_folder_clicked.connect(self._move_all_in_this_folder)
        self.selection_panel.folder_structure_changed.connect(self._on_folder_structure_changed)
        self.selection_panel.type_changed.connect(self._on_type_changed)
        self.selection_panel.year_changed.connect(self._on_year_changed)
        self.selection_panel.status_requested.connect(lambda text: self.show_status(text, 5000))
        root.addWidget(self.selection_panel)

        # Action Panel
        self.action_panel = ActionPanel()
        self.action_panel.delete_clicked.connect(self._on_delete_clicked)
        self.action_panel.flat_folder_clicked.connect(self._on_flat_folder_clicked)
        root.addWidget(self.action_panel)

        # Queue / Character Panel
        self.queue_panel = QueuePanel()
        self.queue_panel.set_hide_secure(self._hide_secure)
        self.queue_panel.characters_updated.connect(self._update_character_buttons)
        self.queue_panel.character_updated.connect(self._on_single_character_updated)
        self.queue_panel.file_double_clicked.connect(self._on_queue_file_double_clicked)
        self.queue_panel.movings_minimized_changed.connect(self._on_movings_minimized_changed)
        root.addWidget(self.queue_panel)
        
        main_vbox.addLayout(root, 1)

        self.status_bar = QStatusBar()
        self.status_bar.setSizeGripEnabled(False)
        main_vbox.addWidget(self.status_bar)
        self.status_bar.showMessage("Listo", 2000) 
        self.status_bar.setStyleSheet(load_stylesheet("main_window.css"))
        
        self.retranslate_ui()
        self._update_undo_button_tooltip()
        
        self._pending_scheduler = PendingScheduler(self._run_pendings, self)
        self._apply_pending_schedule_state()
        
        if hasattr(self, "_movings_minimized"):
            self.queue_panel.set_movings_minimized(self._movings_minimized)

        # Initial size adjustment
        self.resize(self.base_width + self.queue_panel.width(), self.base_height)

    def _update_undo_button_tooltip(self):
        last_move = self.background_move_mgr._history.get_last_move()
        if last_move:
            dest_path = Path(last_move["dst"])
            tooltip_text = f"{self.loc.get('btn_undo')}: {dest_path.name}"
            self.btn_undo.setToolTip(tooltip_text)
            self.btn_undo.setEnabled(True)
        else:
            self.btn_undo.setToolTip("")
            self.btn_undo.setEnabled(False)

    def show_status(self, text: str, ms: int = 5000):
        self.status_bar.showMessage(text, ms)
    
    def _load_config(self):
        try:
            if config.CONFIG_PATH.exists():
                with config.CONFIG_PATH.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                self._hide_secure = data.get("hide_secure", False)
                self._post_action_mode = data.get("post_action_mode", "none")
                self._movings_minimized = data.get("movings_minimized", False)
                
                self._pending_auto_run_enabled = data.get("auto_run_pendings", False)
                pending_time_str = data.get("auto_run_pendings_time", "20:15")
                self._pending_auto_run_time = QTime.fromString(pending_time_str, "HH:mm")
                if not self._pending_auto_run_time.isValid():
                    self._pending_auto_run_time = QTime(20, 15)
                
        except Exception:
            logging.exception("Failed to load config")

    def _save_config(self):
        try:
            data = {}
            if config.CONFIG_PATH.exists():
                with config.CONFIG_PATH.open('r', encoding='utf-8') as f:
                    data = json.load(f)
            data["hide_secure"] = self._hide_secure
            data["post_action_mode"] = self._post_action_mode
            data["movings_minimized"] = getattr(self, "_movings_minimized", False)
            data["auto_run_pendings"] = getattr(self, "_pending_auto_run_enabled", False)
            data["auto_run_pendings_time"] = getattr(self, "_pending_auto_run_time", QTime(20, 15)).toString("HH:mm")
            with config.CONFIG_PATH.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception:
            logging.exception("Failed to save config")

    def _on_movings_minimized_changed(self, minimized: bool):
        self._movings_minimized = minimized
        self._save_config()

    def _apply_pending_schedule_state(self):
        if not hasattr(self, "chk_auto_run_pendings") or not hasattr(self, "time_auto_run_pendings"):
            return

        self.chk_auto_run_pendings.blockSignals(True)
        self.time_auto_run_pendings.blockSignals(True)

        self.chk_auto_run_pendings.setChecked(self._pending_auto_run_enabled)
        self.time_auto_run_pendings.setTime(self._pending_auto_run_time)

        self.chk_auto_run_pendings.blockSignals(False)
        self.time_auto_run_pendings.blockSignals(False)

        if self._pending_scheduler is not None:
            self._pending_scheduler.configure(
                self.chk_auto_run_pendings.isChecked(),
                self.time_auto_run_pendings.time(),
            )

    def _on_pending_schedule_changed(self, *args):
        self._pending_auto_run_enabled = self.chk_auto_run_pendings.isChecked()
        self._pending_auto_run_time = self.time_auto_run_pendings.time()
        self._save_config()

        if self._pending_scheduler is not None:
            self._pending_scheduler.configure(
                self._pending_auto_run_enabled,
                self._pending_auto_run_time,
            )

    def _on_secure_changed(self, state):
        self._hide_secure = (state == Qt.CheckState.Checked.value or state is True)
        self.queue_panel.set_hide_secure(self._hide_secure)
        if hasattr(self, "action_panel") and self.action_panel is not None:
            self.action_panel._hide_secure = self._hide_secure
            self.action_panel.load_preview()
        self._save_config()

    def _on_blur_level_changed(self, value: int):
        config.BLUR_LEVEL = value
        if hasattr(self, "action_panel") and self.action_panel is not None:
            self.action_panel.load_preview()
        if hasattr(self, "queue_panel") and self.queue_panel is not None:
            self.queue_panel.queue_list_widget.itemDelegate()._thumb_cache.clear()
            self.queue_panel.queue_list_widget.viewport().update()
        
    def _on_post_action_changed(self, mode: str):
        self._post_action_mode = mode if mode in ("open_file", "open_folder", "none") else "none"
        self._save_config()

        if mode == "open_file":
            self.show_status(
                self.loc.get("status_post_action_open_file")
            )

        elif mode == "open_folder":
            self.show_status(
                self.loc.get("status_post_action_open_folder")
            )

        else:
            self.show_status(
                self.loc.get("status_post_action_none")
            )

    def _setup_server(self):
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_server_connection)
        server_name = "CatchEtudeCommandServer"
        QLocalServer.removeServer(server_name)
        if not self._server.listen(server_name):
            logging.error(f"Server could not start: {self._server.errorString()}")

    def _on_new_server_connection(self):
        client_socket = self._server.nextPendingConnection()
        client_socket.readyRead.connect(lambda: self._read_server_data(client_socket))

    def _read_server_data(self, socket):
        data = socket.readAll().data().decode('utf-8')
        try:
            cmd = json.loads(data)
            if cmd.get("cmd") == "capture_ui_render":
                self._capture_ui_render()
                socket.disconnectFromServer()
                return

            path = cmd.get("path")
            hide_secure = cmd.get("hide_secure", True)
            if path and os.path.exists(path):
                self._hide_secure = hide_secure
                self.hide_secure_cb.setChecked(self._hide_secure)
                self.queue_panel.set_hide_secure(self._hide_secure)
                if hasattr(self, "action_panel") and self.action_panel is not None:
                    self.action_panel._hide_secure = self._hide_secure
                    self.action_panel.load_preview()
                self._save_config()
                p = Path(path)
                if p.is_dir():
                    self._process_pending_folder(p)
                else:
                    self.state_manager.enqueue_file(p)
        except Exception:
            logging.exception("Failed to process server command")
        socket.disconnectFromServer()

    def _capture_ui_render(self):
        try:
            pixmap = self.grab()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"catchetude_ui_render_{timestamp}.png"
            dest_path = resolve_duplicate(config.DOWNLOADS / filename)
            pixmap.save(str(dest_path), "PNG")
            logging.info(f"UI render captured and saved to {dest_path}")
            self.show_status(f"UI render guardado en Downloads: {dest_path.name}")
        except Exception:
            logging.exception("Failed to capture UI render")

    def retranslate_ui(self):
        self.btn_reload.setText(self.loc.get("btn_reload"))
        self.btn_reload.setToolTip(self.loc.get("tooltip_reload"))
        self.hide_secure_cb.setText(self.loc.get("btn_secure"))
        self.chk_auto_run_pendings.setText("Autoexecure Pendings")
        self.btn_hide.setText(self.loc.get("btn_hide"))
        self.btn_undo.setText(self.loc.get("btn_history"))
        self.btn_lang.setText(self.loc.get("lang_toggle"))
        self.selection_panel.retranslate_ui()
        self.action_panel.retranslate_ui()
        self.queue_panel.retranslate_ui()
        if hasattr(self, '_pending_dialog'):
            self._pending_dialog.retranslate_ui()
        self._update_undo_button_tooltip()

    def _on_lang_toggle(self):
        self.loc.toggle_lang()
        self.retranslate_ui()
        self._build_tray()

    def _on_delete_clicked(self):
        if not self.filepath or self.filepath.is_dir():
            return

        send_character_service_command("pause")
        try:
            if not self.filepath.exists():
                self.state_manager.discard_missing_active_file(
                    f"Archivo ya no existe: {self.filepath.name}"
                )
                self.queue_panel.set_progress(0)
                self.show_status(f"Archivo ya no existe: {self.filepath.name}", 5000)
                return

            if delete_to_recycle_bin(self.filepath):
                self.state_manager.discard_active_file()
                self.queue_panel.set_progress(0)
            else:
                self.show_status("No se pudo eliminar el archivo.", 5000)

        finally:
            send_character_service_command("resume")

    def _on_undo_clicked(self):
        send_character_service_command("pause")
        try:
            if not self.background_move_mgr.undo_last_move():
                QtWidgets.QMessageBox.information(self, "Undo", "Nothing to undo or file no longer exists.")
            else:
                self._build_tray()
                self._update_undo_button_tooltip()
                self._bring_and_center()
        finally:
            send_character_service_command("resume")

    def _on_context_undo_clicked(self):
        send_character_service_command("pause")
        try:
            if not self.background_move_mgr.undo_last_move():
                self.show_status(self.loc.get("msg_nothing_to_undo"), 5000)
            else:
                self._build_tray()
                self._update_undo_button_tooltip()
                self._bring_and_center()
        finally:
            send_character_service_command("resume")

    def _on_tray_undo_clicked(self):
        send_character_service_command("pause")
        try:
            if not self.background_move_mgr.undo_last_move():
                QtWidgets.QMessageBox.information(self, "Undo", "Nothing to undo or file no longer exists.")
            else:
                with self.state_manager._lock:
                    queue_list = list(self.state_manager._queue_list)
                if queue_list:
                    first_file = queue_list[0]
                    self.state_manager.select_queued_file(first_file)
                self._build_tray()
                self._update_undo_button_tooltip()
                self._bring_and_center()
        finally:
            send_character_service_command("resume")

    def _on_reload_clicked(self):
        reply = QtWidgets.QMessageBox.question(
            self,
            self.loc.get("btn_reload"),
            self.loc.get("msg_reload_confirm"),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            self.filepath = None
            self.action_panel.clear()
            self.state_manager.reset_queue_and_rescan()
            self._bring_and_center()

    def _on_exit_clicked(self):
        if not self.background_move_mgr.is_idle():
            logging.warning("Exit blocked: active background file moves are in progress.")
            QtWidgets.QMessageBox.warning(
                self,
                self.loc.get("msg_cannot_close_moving_title") or "Operación en progreso",
                self.loc.get("msg_cannot_close_moving") or "No se puede cerrar la aplicación mientras se realiza un movimiento de archivos. Por favor, espere a que termine."
            )
            return

        reply = QtWidgets.QMessageBox.question(
            self, self.loc.get("msg_exit_title"), self.loc.get("msg_exit_confirm"),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            QApplication.quit()

    def closeEvent(self, event):
        if not self.background_move_mgr.is_idle():
            logging.warning("Close event blocked: active background file moves are in progress.")
            QtWidgets.QMessageBox.warning(
                self,
                self.loc.get("msg_cannot_close_moving_title") or "Operación en progreso",
                self.loc.get("msg_cannot_close_moving") or "No se puede cerrar la aplicación mientras se realiza un movimiento de archivos. Por favor, espere a que termine."
            )
            event.ignore()
        else:
            self._closing = True
            self.background_move_mgr.stop_accepting_new_moves()
            self.background_move_mgr.wait_for_done(30000)
            self.background_move_mgr.move_started.disconnect(self._on_background_move_started)
            self.background_move_mgr.move_progress.disconnect(self._on_background_move_progress)
            self.background_move_mgr.move_finished.disconnect(self._on_background_move_finished)
            event.accept()

    def _manual_hide(self):
        self.hide()
        if self.state_manager.has_pending_work():
            self._pending_dialog.show()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_tray_show_hide_action()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._update_tray_show_hide_action()

    def _toggle_show_hide(self):
        if self.isVisible():
            self._manual_hide()
        else:
            self._bring_and_center()

    def _update_tray_show_hide_action(self):
        if hasattr(self, 'tray_mgr'):
            self.tray_mgr.update_show_hide_action()

    def _build_tray(self):
        if hasattr(self, 'tray_mgr'):
            self.tray_mgr.build_tray()

    def _show_plugin_manager(self):
        if hasattr(self, "_plugin_dialog") and self._plugin_dialog is not None and self._plugin_dialog.isVisible():
            self._plugin_dialog.raise_()
            self._plugin_dialog.activateWindow()
            return

        from plugin_manager_dialog import PluginManagerDialog
        # Find global plugin_mgr if present, or create local reference
        plugin_mgr = getattr(sys.modules["__main__"], "plugin_mgr", None)
        if not plugin_mgr:
            from plugin_manager import PluginManager
            plugin_mgr = PluginManager()

        self._plugin_dialog = PluginManagerDialog(plugin_mgr, self.loc, self)
        self._plugin_dialog.show()

    def _open_last_chosen(self):
        last_move = self.background_move_mgr._history.get_last_move()
        if not last_move:
            return
        dest_dir = Path(last_move["dst"]).parent
        if dest_dir.exists():
            os.startfile(dest_dir)
    
    def _open_appdta_folder(self):
        os.startfile(config.APPDATA_DIR)
    
    def _open_recent_file(self):
        last_move = self.background_move_mgr._history.get_last_move()
        if not last_move:
            return
        recent_file = Path(last_move["dst"])
        if recent_file.exists():
            os.startfile(str(recent_file))
        else:
            self._show_warning_message("El archivo reciente ya no existe.")
        
    def _show_warning_message(self, text):
        QMessageBox.warning(self, "Aviso", text)
    
    
    def _check_destination_collision(self, candidate: Path, 
                                     allow_retry: bool = False) -> tuple[str, Optional[Path]]:
        if not candidate.exists():
            return "move", candidate

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Archivo con el mismo nombre")
        box.setText(f"Ya existe un archivo con el mismo nombre:\n{candidate.name}")
        box.setInformativeText("Elige qué hacer.")

        btn_move = box.addButton("Mover de todas formas", QMessageBox.ButtonRole.AcceptRole)
        btn_delete = box.addButton("Eliminar duplicado", QMessageBox.ButtonRole.DestructiveRole)
        btn_open = box.addButton("Abrir archivo existente", QMessageBox.ButtonRole.ActionRole)
        btn_other = None
        
        if allow_retry:
            btn_other = box.addButton("Elegir otra carpeta", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = box.addButton(QMessageBox.StandardButton.Cancel)

        box.setDefaultButton(btn_move)
        box.exec()

        clicked = box.clickedButton()

        if clicked == btn_delete:
            self.selection_panel.set_subfolders_enabled(True)
            try:
                if delete_to_recycle_bin(candidate):
                    return "move", candidate
            except Exception:
                logging.exception("Failed to delete existing destination file")

            self._show_warning_message(f"No se pudo eliminar el archivo existente:\n{candidate.name}")
            return "cancel", None

        if clicked == btn_open:
            self.selection_panel.set_subfolders_enabled(True)
            try:
                os.startfile(str(candidate))
            except OSError as exc:
                self._show_warning_message(f"No se pudo abrir el archivo existente:\n{exc}")
            return "open", None

        if allow_retry and btn_other is not None and clicked == btn_other:
            self.selection_panel.set_subfolders_enabled(True)
            return "retry", None

        if clicked == btn_cancel:
            self.selection_panel.set_subfolders_enabled(True)
            return "cancel", None

        return "move", resolve_duplicate(candidate)

    def _show_logs(self):
        socket = QLocalSocket()
        socket.connectToServer("CatchEtudeLogServer")
        if socket.waitForConnected(100):
            data = json.dumps({"cmd": "show"})
            socket.write(data.encode('utf-8'))
            socket.waitForBytesWritten(100)
            socket.disconnectFromServer()

    def _open_settings_dialog(self):
        settings_script = Path(__file__).resolve().parent / "settings_dialog.pyw"

        python_exe = sys.executable
        if python_exe.lower().endswith("python.exe"):
            python_exe = python_exe[:-10] + "pythonw.exe"

        subprocess.Popen(
            [python_exe, str(settings_script)],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
        )

    def _bring_and_center(self):
        if hasattr(self, '_pending_dialog'):
            self._pending_dialog.hide()
        if self.isMinimized():
            self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.show()
        screen = self.screen().availableGeometry()
        size = self.geometry()
        x = (screen.width() - size.width()) // 2
        y = (screen.height() - size.height()) // 2
        self.move(x, y)
        self.raise_()
        self.activateWindow()

    def _restart_service(self):
        if not self.background_move_mgr.is_idle():
            logging.warning("Restart service blocked: active background file moves are in progress.")
            QtWidgets.QMessageBox.warning(
                self,
                self.loc.get("msg_cannot_close_moving_title") or "Operación en progreso",
                self.loc.get("msg_cannot_close_moving") or "No se puede cerrar la aplicación mientras se realiza un movimiento de archivos. Por favor, espere a que termine."
            )
            return

        pid = os.getpid()
        script_path = str(Path(sys.argv[0]).resolve())
        flags = 0x00000010 | 0x08000000
        try:
            subprocess.Popen([sys.executable, config.RESTART_APP_DIR, str(pid), script_path], creationflags=flags)
        except OSError as e:
            logging.warning(f"Failed to restart with flags, trying without: {e}")
            try:
                subprocess.Popen([sys.executable, config.RESTART_APP_DIR, str(pid), script_path])
            except Exception as e2:
                logging.error(f"Failed to restart service even without flags: {e2}")
        except Exception as e:
            logging.error(f"Unexpected error restarting service: {e}")
        QApplication.quit()

    def _rescan_downloads(self):
        run_in_threadpool(scan_existing_downloads, self.state_manager)

    def _on_order_pending_clicked(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Process", str(config.DOWNLOADS))
        if folder: self._process_pending_folder(Path(folder))

    def _run_pendings(self):
        try:
            pendings_script = str(Path(__file__).resolve().parent / "pendings_exec.pyw")
            python_exe = sys.executable
            if python_exe.lower().endswith("python.exe"):
                python_exe = python_exe[:-10] + "pythonw.exe"
            subprocess.Popen([python_exe, pendings_script], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        except Exception:
            logging.exception("Failed to run pendings script")

    def _process_pending_folder(self, folder: Path):
        def worker():
            try:
                logging.info(f"Processing pending folder: {folder}")
                files = []
                try:
                    for f in folder.rglob("*"):
                        files.append(f)
                except Exception as e:
                    logging.warning(f"Error while scanning folder {folder}: {e}")

                try:
                    files.sort()
                except Exception as e:
                    logging.warning(f"Error sorting files: {e}")

                to_enqueue = []
                for f in files:
                    try:
                        if f.is_file() and not is_temporary(f):
                            to_enqueue.append(f)
                    except Exception as e:
                        logging.debug(f"Error checking file {f}: {e}")

                if to_enqueue:
                    self.state_manager.enqueue_files(to_enqueue)
                    logging.info(f"Enqueued {len(to_enqueue)} files from folder: {folder}")
                else:
                    logging.info(f"No files to enqueue from folder: {folder}")
            except Exception:
                logging.exception("Failed to process pending folder")
        run_in_threadpool(worker)

    def _set_ui_enabled_for_move(self, enabled: bool):
        if self.filepath and self.filepath.is_dir():
            self.action_panel.btn_delete.setEnabled(False)
            self.action_panel.rename_input.setEnabled(False)
            self.selection_panel.setEnabled(False)
            return

        self.selection_panel.setEnabled(True)
        self.action_panel.btn_delete.setEnabled(enabled and bool(self.filepath))
        if not enabled:
            self.btn_undo.setEnabled(False)
        else:
            self._update_undo_button_tooltip()
        self.selection_panel.set_subfolders_enabled(enabled)

    @QtCore.pyqtSlot(str)
    def on_file_detected(self, path_str: str):
        logging.info("FD 1")

        p = Path(path_str)

        logging.info("FD 2")
        if not p.exists():
            logging.info("FD 2a")
            return

        logging.info("FD 3")
        if self.state_manager.current_state() != State.FILE_DETECTED:
            logging.info("FD 3a")
            return

        logging.info("FD 4")
        if not self.state_manager.declare_user_deciding():
            logging.info("FD 4a")
            return

        logging.info("FD 5")

        logging.info("FD 6")
        self._update_undo_button_tooltip()

        logging.info("FD 7")
        self.filepath = p

        logging.info("FD 8")
        self.action_panel.set_file(p, self._hide_secure)

        logging.info("FD 9")
        self.queue_panel.set_progress(0)

        logging.info("FD 10")
        if p.is_dir():
            self.selection_panel.setEnabled(False)
            autoflat_targets = [f.strip().lower() for f in getattr(config, "AUTOFLAT_FOLDERS", "").split("/") if f.strip()]
            if p.name.lower() in autoflat_targets:
                logging.info(f"Auto-flattening folder: {p.name}")
                folder = p
                self.action_panel.suspend_preview_loading(folder)
                self._set_ui_enabled_for_move(False)

                def autoflat_worker():
                    moved, success = flatten_single_folder(folder)
                    if moved:
                        self.state_manager.enqueue_files(moved)

                    def on_autoflat_finish():
                        if success:
                            self.action_panel.clear()
                            self.filepath = None
                            self.state_manager.discard_active_file()
                        else:
                            self._set_ui_enabled_for_move(True)
                            self.show_status(f"Auto-flat falló para {folder.name}. Por favor, hágalo manualmente.", 5000)

                    QtCore.QTimer.singleShot(0, on_autoflat_finish)

                run_in_threadpool(autoflat_worker)
                return
        else:
            self.selection_panel.setEnabled(True)
            self.selection_panel.refresh_classification_ui()

        logging.info("FD 11")
        sel = self.selection_panel.get_selection()

        logging.info("FD 12")
        t = sel["type"]
        if t in (2, 3, 4, 7, 8) and not is_internal_available():
            if not self._internal_warned:
                self._internal_warned = True
                QtWidgets.QMessageBox.warning(self, "Almacenamiento no disponible", "El disco interno (E:\\_Internal) no está conectado.")
            self.selection_panel.list_sub.clear()
            self.selection_panel.list_sub.setEnabled(False)
            self.selection_panel.list_year.setEnabled(False)

        logging.info("FD 13")
        logging.info("FD 14")

        logging.info("FD 15")
        if self._hide_t_active:
            self._restore_from_hide_t()
        else:
            self._bring_and_center()

        logging.info("FD 16")
        if self._bulk_subfolder_name:
            self._move_to_subfolder(self._bulk_subfolder_name)
        else:
            # Prevent rapid clicks: disable inputs for configured delay time
            self._set_ui_enabled_for_move(False)
            QtCore.QTimer.singleShot(config.TIMER_GC, lambda: self._set_ui_enabled_for_move(True))

        logging.info("FD END")

    def _on_type_changed(self, t: int):
        if t == 2:
            sel = self.selection_panel.get_selection()
            if sel['year']:
                self._on_year_changed(sel['year'])

        if t in (2, 3, 4, 7, 8) and not is_internal_available():
            if not self._internal_warned:
                self._internal_warned = True
                QtWidgets.QMessageBox.warning(self, "Almacenamiento no disponible", "El disco interno (E:\\_Internal) no está conectado.")
            self.selection_panel.list_sub.clear()
            self.selection_panel.list_sub.setEnabled(False)
            self.selection_panel.list_year.setEnabled(False)
            return

    def _on_keep_action_clicked(self, action_name: str):
        if not self.filepath and action_name not in (
            self.loc.get("keep_all_files"),
            self.loc.get("keep_all_files_open_folder"),
            self.loc.get("save_all_another_folder_open_folder"),
            "Keep all files in conflicts",
            "Keep all files in Conflicts and open folder",
            "Save all file in another folder and open folder"
        ):
            return

        post_action = "none"
        if "open this file" in action_name or "open file" in action_name or action_name == self.loc.get("keep_this_file_open_file") or action_name == self.loc.get("save_another_folder_open_file"):
            post_action = "open_file"
        elif "open folder" in action_name or action_name in (
            self.loc.get("keep_this_file_open_folder"),
            self.loc.get("keep_all_files_open_folder"),
            self.loc.get("save_another_folder_open_folder"),
            self.loc.get("save_all_another_folder_open_folder")
        ):
            post_action = "open_folder"

        if action_name in (self.loc.get("keep_this_file"), self.loc.get("keep_this_file_open_file"), self.loc.get("keep_this_file_open_folder"), "Keep this file in Conflicts", "Keep this file in Conflicts and open this file", "Keep this file in Conflicts and open folder"):
            if self.state_manager.current_state() != State.USER_DECIDING:
                logging.error("Keep ignorado: estado inválido")
                return

            decision = {
                "action": "keep",
                "new_name": self.action_panel.get_new_name() or self.filepath.stem,
                "post_action": post_action,
            }
            keep_name = sanitize_windows_filename(decision.get('new_name', self.filepath.stem))
            dest = resolve_duplicate(config.CONFLICTS / (keep_name + self.filepath.suffix))

            logging.info(f"Delegating Keep decision to async background worker for destination: {dest}")
            self._start_move_task(decision, dest)

        elif action_name in (self.loc.get("keep_all_files"), self.loc.get("keep_all_files_open_folder"), "Keep all files in conflicts", "Keep all files in Conflicts and open folder"):
            self._keep_all_queued_files(post_action=post_action)

        elif action_name in (self.loc.get("save_all_another_folder_open_folder"), "Save all file in another folder and open folder"):
            self._save_all_queued_files_custom(post_action=post_action)

        elif action_name in (
            self.loc.get("save_another_folder"),
            self.loc.get("save_another_folder_open_file"),
            self.loc.get("save_another_folder_open_folder"),
            "Save in another folder",
            "Save this file in another folder",
            "Save this file in another folder and open file",
            "Save this file in another folder and open folder"
        ):
            self._on_apply_custom(post_action=post_action)

    def _on_linear_docs_action_clicked(self, action_name: str):
        if not self.filepath:
            return

        if action_name == "Guardar en el año seleccionado":
            selected_year = self.selection_panel.get_selection()["year"] or datetime.now().year
            target_year = selected_year
        else: # "Guardar en el año actual"
            target_year = datetime.now().year

        dt = datetime.fromtimestamp(self.filepath.stat().st_mtime)
        base_year_folder = config.BASE_INTERNAL / str(target_year)
        if not base_year_folder.exists():
            target_year = datetime.now().year
            base_year_folder = config.BASE_INTERNAL / str(target_year)

        prefix = f"{target_year - 2003:02d}"
        base = base_year_folder / f"{prefix}. {config.ACROBAT_FOLDER}"
        month_folder = dt.strftime("%Y-%m")
        dest_dir = base / month_folder
        dest_dir.mkdir(parents=True, exist_ok=True)

        new_name = sanitize_windows_filename(self.action_panel.get_new_name() or self.filepath.stem)
        candidate = dest_dir / (new_name + self.filepath.suffix)

        decision = {
            'action': 'move',
            'movement_type': 7,
            'year': target_year,
            'sub': None,
            'new_name': new_name,
            'post_action': "none",
        }

        action, final_dest = self._check_destination_collision(candidate)
        if action != "move" or final_dest is None:
            return
        self._start_move_task(decision, final_dest)

    def _on_year_changed(self, year: int):
        t = self.selection_panel.get_selection()['type']
        if t == 2:
            self._pending_year = year
            self._year_load_timer.start(400)

    def _on_folder_structure_changed(self):
        sel = self.selection_panel.get_selection()
        t = sel['type']
        year = sel['year']
        if t == 2 and year:
            self._pending_year = year
            self._year_load_timer.start(200) # Faster refresh on manual change

    def _load_characters_for_year(self):
        if self._pending_year is None: return
        self._char_load_generation += 1
        self.queue_panel.request_characters(self._pending_year, self._char_load_generation)

    def _on_queue_file_double_clicked(self, path_str: str):
        p = Path(path_str)
        if not p.exists():
            return
        if self.filepath and self.filepath.is_dir():
            return
        self.state_manager.select_queued_file(p)

    @QtCore.pyqtSlot(list, str)
    def _on_queue_updated(self, queue_list: list[Path], active_path_str: str):
        self.queue_panel.update_queue(queue_list, active_path_str)
        self._update_undo_button_tooltip()

    def _on_single_character_updated(self, c):
        t = self.selection_panel.get_selection()['type']
        if t != 2: return

        folder_name = Path(c.path).name
        try:
            birthday = datetime.fromisoformat(c.birthday_iso)
        except Exception:
            birthday = datetime(1970, 1, 1)
        birthday_fix = "" if not birthday or birthday.year == 1970 else f" · {birthday.strftime('%Y-%m-%d')}"
        num_char = f" · {c.num:02d}" if c.num != 0 else ""
        alter_sh = f"/{c.alter}" if c.name != '_' else ""
        line2 = f"{c.year}{num_char} · {c.name if c.name != '_' else c.alter}{alter_sh}{birthday_fix}"
        real_age = f"{c.age_str} | " if c.age_str else ""
        distance = "" if c.origin_age == 0 else f"d: {(c.year - 2003) - c.origin_age} | "
        oring_age_fix = "" if c.origin_age == 0 else f"a: {c.origin_age} | "
        line3 = f"{real_age}{distance}{oring_age_fix}Files: {c.file_count} | {c.size_mb_str}"
        self.selection_panel.update_subfolder_button(folder_name, line2, line3)

    def _update_character_buttons(self):
        t = self.selection_panel.get_selection()['type']
        if t != 2: return
            
        for c in self.queue_panel.get_characters():
            self._on_single_character_updated(c)

    def _keep_all_queued_files(self, post_action: str = "none"):
        """Queue a keep operation for every file currently in the download queue."""
        sources = self.state_manager.start_all_background_moves()
        if not sources:
            self.show_status("No hay archivos en cola para conservar.", 5000)
            return

        tasks = []
        for source in sources:
            if not source.exists() or source.is_dir():
                self.state_manager.fail_background_move(source)
                continue
            try:
                stat = source.stat()
                source_meta = {
                    "atime": stat.st_atime,
                    "mtime": stat.st_mtime,
                    "ctime": getattr(stat, "st_birthtime", stat.st_ctime),
                }
            except Exception:
                logging.exception("Could not read metadata for queued keep: %s", source)
                self.state_manager.fail_background_move(source)
                continue

            destination = resolve_duplicate(config.CONFLICTS / source.name)
            tasks.append((source, destination, source_meta))

        if not tasks:
            self.show_status("No se pudieron preparar archivos para conservar.", 5000)
            return

        send_character_service_command("pause")
        for source, destination, source_meta in tasks:
            self.background_move_mgr.enqueue_move(
                source,
                destination,
                {"action": "keep", "new_name": source.stem, "post_action": post_action},
                source_meta,
            )

        self.filepath = None
        self.action_panel.clear()
        self.show_status(f"Conservando {len(tasks)} archivos de la cola.", 5000)

    def _save_all_queued_files_custom(self, post_action: str = "none"):
        """Queue a custom move operation for every file currently in the download queue."""
        folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder", str(config.DOWNLOADS))
        if not folder:
            return

        dest_dir = Path(folder)
        sources = self.state_manager.start_all_background_moves()
        if not sources:
            self.show_status("No hay archivos en cola para guardar.", 5000)
            return

        tasks = []
        for source in sources:
            if not source.exists() or source.is_dir():
                self.state_manager.fail_background_move(source)
                continue
            try:
                stat = source.stat()
                source_meta = {
                    "atime": stat.st_atime,
                    "mtime": stat.st_mtime,
                    "ctime": getattr(stat, "st_birthtime", stat.st_ctime),
                }
            except Exception:
                logging.exception("Could not read metadata for queued custom move: %s", source)
                self.state_manager.fail_background_move(source)
                continue

            destination = resolve_duplicate(dest_dir / source.name)
            tasks.append((source, destination, source_meta))

        if not tasks:
            self.show_status("No se pudieron preparar archivos para guardar.", 5000)
            return

        send_character_service_command("pause")
        for source, destination, source_meta in tasks:
            self.background_move_mgr.enqueue_move(
                source,
                destination,
                {"action": "move_custom", "custom_dir": str(dest_dir), "new_name": source.stem, "post_action": post_action},
                source_meta,
            )

        self.filepath = None
        self.action_panel.clear()
        self.show_status(f"Guardando {len(tasks)} archivos en {dest_dir.name}.", 5000)

    def _move_to_subfolder(self, sub_name: str, post_action: str = "none"):
        if not self.filepath or self.filepath.is_dir():
            return
        
        self.selection_panel.set_subfolders_enabled(False)
        sel = self.selection_panel.get_selection()
        
        decision = {
            'action': 'move',
            'movement_type': sel['type'],
            'year': sel['year'],
            'sub': sub_name,
            'new_name': self.action_panel.get_new_name() or self.filepath.stem,
            'post_action': post_action,
        }
        
        candidate = compute_destination(decision, self.filepath)
        action, final_dest = self._check_destination_collision(candidate)
        if action != "move" or final_dest is None:
            return
        self._start_move_task(decision, final_dest)

    def _move_all_in_this_folder(self, sub_name: str, post_action: str = "none"):
        self._bulk_subfolder_name = sub_name
        self._move_to_subfolder(sub_name, post_action=post_action)

    def _move_and_enable_secure(self, sub_name: str):
        if not self.hide_secure_cb.isChecked():
            self.hide_secure_cb.setChecked(True)
        self._move_to_subfolder(sub_name)

    def _on_apply_custom(self, post_action: str = "none"):
        if not self.filepath or self.filepath.is_dir():
            return
        
        folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder", str(self.filepath.parent))
        
        if not folder: 
            return
        
        decision = {
            'action': 'move_custom',
            'custom_dir': folder,
            'new_name': self.action_panel.get_new_name() or self.filepath.stem,
            'post_action': post_action,
        }
                
        newname = sanitize_windows_filename(decision['new_name'])

        while True:
            candidate = Path(folder) / (newname + self.filepath.suffix)
            action, final_dest = self._check_destination_collision(candidate, allow_retry=True)

            if action == "retry":
                folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder", str(self.filepath.parent))
                if not folder:
                    return
                continue

            if action != "move" or final_dest is None:
                return

            self._start_move_task(decision, final_dest)
            return
        

    def _on_background_move_started(self, src: Path, dst: Path):
        if self._closing:
            return
        self.queue_panel.queue_movings_widget.add_movement(src, dst)

    @QtCore.pyqtSlot(Path, int)
    def _on_background_move_progress(self, src: Path, val: int):
        if self._closing:
            return
        self.queue_panel.queue_movings_widget.update_progress(src, val)
        if self.filepath == src:
            self.queue_panel.set_progress(val)

    @QtCore.pyqtSlot(Path, Path, bool, str, dict, dict)
    def _on_background_move_finished(self, src: Path, dst: Path, ok: bool, msg: str, src_meta: dict, decision: dict):
        if self._closing:
            return
        logging.info(f"[MainWindow][finish-boundary] background finish received: {src} -> {dst} ok={ok} msg={msg}")
        logging.info("[MainWindow][finish-boundary] resume character service start")
        send_character_service_command("resume")
        logging.info("[MainWindow][finish-boundary] resume character service done")
        logging.info(f"[MainWindow][finish-boundary] remove moving UI item start: {src}")
        self.queue_panel.queue_movings_widget.remove_movement(src)
        logging.info(f"[MainWindow][finish-boundary] remove moving UI item done: {src}")
        
        if ok:
            logging.info(f"[MainWindow][finish-boundary] finalize ok move start: {src}")
            self.background_move_mgr.finalize_move(src, dst, src_meta, decision.get("post_action", "none"))
            logging.info(f"[MainWindow][finish-boundary] finalize ok move done: {src}")
            self._build_tray()
        else:
            if msg == "TIMESTAMP_RESTORE_FAILED":
                retry = QtWidgets.QMessageBox.question(
                    self,
                    "Restaurar fecha",
                    "El archivo ya fue transferido, pero no se pudo restaurar su fecha de creación. ¿Deseas reintentar la restauración de fecha?",
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                    QtWidgets.QMessageBox.StandardButton.Yes
                )
                if retry == QtWidgets.QMessageBox.StandardButton.Yes:
                    try:
                        from wctime import setctime_blocking
                        os.utime(dst, (src_meta["atime"], src_meta["mtime"]))
                        setctime_blocking(str(dst), src_meta["ctime"])
                        logging.info(f"Timestamp retry succeeded for moved file: {dst}")
                    except Exception:
                        logging.exception(f"Timestamp retry failed for moved file: {dst}")
                        self.show_status("No se pudo restaurar la fecha; se conservará el archivo movido.", 5000)

                logging.info(f"[MainWindow][finish-boundary] finalize timestamp-failed move start: {src}")
                self.background_move_mgr.finalize_move(src, dst, src_meta, decision.get("post_action", "none"))
                logging.info(f"[MainWindow][finish-boundary] finalize timestamp-failed move done: {src}")
                self._build_tray()
            elif msg == "FILE_LOCKED":
                self.show_status(self.loc.get("msg_file_locked"), 5000)
                self.state_manager.fail_background_move(src)
            else:
                self.state_manager.fail_background_move(src)

        self._hide_if_idle()

    def _start_move_task(self, decision: dict, final_dest: Path):
        src = self.filepath
        if not src: 
            return
        
        if is_file_locked(src):
            self.show_status(self.loc.get("msg_file_locked"), 5000)
            return
        
        self.action_panel.suspend_preview_loading(src)
        send_character_service_command("pause")

        try:
            src_stat = src.stat()
            src_meta = {
                "atime": src_stat.st_atime,
                "mtime": src_stat.st_mtime,
                "ctime": getattr(src_stat, "st_birthtime", src_stat.st_ctime),
            }
            
        except Exception:
            logging.exception(f"Error in _start_move_task for {src}")
            send_character_service_command("resume")
            self.state_manager.discard_active_file()
            self.action_panel.clear()
            return

        # Enqueue the move task inside our new BackgroundMoveManager
        self.background_move_mgr.enqueue_move(src, final_dest, decision, src_meta)

        if not self.state_manager.start_background_move(src):
            logging.warning(f"StateManager failed to start background move for {src}")
            return

        self.filepath = None
        self.action_panel.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.action_panel.load_preview()

    def _hide_if_idle(self):
        if self.state_manager.current_state() == State.IDLE and not self.state_manager.has_pending_work() and self.background_move_mgr.is_idle():
            self._flush_post_actions()
            self._bulk_subfolder_name = None
            self.action_panel.clear()
            self.filepath = None
            if hasattr(self, '_pending_dialog'):
                self._pending_dialog.hide()
            self.hide()

    def _queue_or_run_post_action(self, final_path, post_action: str):
        if post_action not in ("open_file", "open_folder"):
            return

        if not final_path:
            return

        try:
            path = final_path if isinstance(final_path, Path) else Path(str(final_path))
        except Exception:
            logging.exception("Invalid final_path for post action")
            return

        target = path if post_action == "open_file" else path.parent

        key = str(target.resolve()) if target.exists() else str(target)

        if self._bulk_subfolder_name:
            self._pending_post_actions[key] = (target, post_action)
            return

        self._run_post_action(target, post_action)

    def _run_post_action(self, target, post_action: str):
        try:
            target = target if isinstance(target, Path) else Path(str(target))
            if target.exists():
                os.startfile(str(target))
                self._consume_post_action()
        except Exception:
            logging.exception(f"Failed post action {post_action} for {target}")

    def _flush_post_actions(self):
        if not self._pending_post_actions:
            return

        pending = list(self._pending_post_actions.values())
        self._pending_post_actions.clear()

        for target, post_action in pending:
            self._run_post_action(target, post_action)
        
        if pending:
            self._consume_post_action()

    def _consume_post_action(self):
        mode = self.action_panel.get_post_action_mode()

        if mode == "none":
            return

        self._post_action_consumed = True

        self.action_panel.blockSignals(True)
        self.action_panel.set_post_action_mode("none")
        self.action_panel.blockSignals(False)

        self._post_action_mode = "none"
        self._save_config()

        try:
            self.show_status(
                self.loc.get("status_post_action_consumed"),
                8000
            )
        except Exception:
            logging.exception("Failed to show post-action reset notification")

    def _on_flat_folder_clicked(self):
        if not self.filepath:
            self.show_status("No hay carpeta activa", 5000)
            return

        if not self.filepath.is_dir():
            self.show_status("Es un archivo", 5000)
            return

        folder = self.filepath
        self.action_panel.suspend_preview_loading(folder)
        self._set_ui_enabled_for_move(False)

        def flat_folder_worker():
            moved, success = flatten_single_folder(folder)
            if moved:
                self.state_manager.enqueue_files(moved)

            def on_flat_finish():
                if success:
                    self.action_panel.clear()
                    self.filepath = None
                    self.state_manager.discard_active_file()
                else:
                    self._set_ui_enabled_for_move(True)
                    self.show_status(f"Flat folder falló para {folder.name}.", 5000)

            QtCore.QTimer.singleShot(0, on_flat_finish)

        run_in_threadpool(flat_folder_worker)

    def _on_hide_t_clicked(self):
        self._hide_t_active = True
        self.hide()

        if hasattr(self, "_pending_dialog"):
            self._pending_dialog.hide()

        self._hide_t_banner.start(5)


    def _restore_from_hide_t(self):
        self._hide_t_active = False

        if hasattr(self, "_hide_t_banner"):
            self._hide_t_banner.stop()

        self._bring_and_center()
