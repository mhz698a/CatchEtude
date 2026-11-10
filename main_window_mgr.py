"""
Main Window manager for CatchEtude.
Gestor de la ventana principal para CatchEtude.
"""

import os
import sys
import logging
import json
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Callable, Optional

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QFileDialog,
    QHBoxLayout, QVBoxLayout, QMessageBox, QStatusBar, 
    QCheckBox, QTimeEdit, QSpinBox
)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtCore import Qt, QTime

import config
from utils import (
    resolve_duplicate, 
    configure_dwm_thumbnail_behavior, is_internal_available,
    sanitize_windows_filename, is_temporary,
    is_file_locked, delete_to_recycle_bin, run_in_threadpool,
    flatten_single_folder
)
from state_manager import StateManager, State
from ui_utils_mgr import load_stylesheet
from fallback_utils import compute_destination
from app_signals_mgr import AppSignals
from localization import LocalizationManager
from pending_scheduler_mgr import PendingScheduler
from selection_panel_mgr import SelectionPanel
from action_panel_mgr import ActionPanel
from queue_panel_mgr import QueuePanel
from queue_rename_dialog import QueueRenameDialog
from service_mgr import send_character_service_command
from pending_dialog import PendingDialog
from temporary_hide_banner_mgr import TemporaryHideBanner
from background_move_mgr import BackgroundMoveManager
from tray_menu_mgr import TrayMenuManager
from duplication_mgr import _DuplicateDeleteWorker, _QueueFileCopyWorker


class _FlattenOperationSignals(QtCore.QObject):
    progress = QtCore.pyqtSignal(int, int, str, str)
    finished = QtCore.pyqtSignal(object, bool, str)


class MainWindow(QWidget):
    """
    Main UI window for CatchEtude.
    Ventana principal de la interfaz de CatchEtude.
    """
    def __init__(self, state_manager: StateManager, signals: AppSignals, plugin_mgr=None):
        super().__init__()
        self.state_manager = state_manager
        self.signals = signals
        self.plugin_mgr = plugin_mgr
        self.loc = LocalizationManager()
        
        self.background_move_mgr = BackgroundMoveManager(self.state_manager, self)
        self.background_move_mgr.move_started.connect(self._on_background_move_started)
        self.background_move_mgr.move_progress.connect(self._on_background_move_progress)
        self.background_move_mgr.move_finished.connect(self._on_background_move_finished)
        self.background_move_mgr.undo_started.connect(self._on_undo_started)
        self.background_move_mgr.undo_progress.connect(self._on_undo_progress)
        self.background_move_mgr.undo_finished.connect(self._on_undo_finished)
        self._closing = False
        self._undo_progress_dialog = None
        self._undo_select_first_after_finish = False
        self._flatten_operation = None
        self._duplicate_delete_operation_counter = 0
        self._duplicate_delete_operations: dict[int, dict] = {}
        self._queue_copy_operation_counter = 0
        self._queue_copy_operations: dict[int, dict] = {}
        
        self.signals.file_detected.connect(self.on_file_detected)
        self.signals.queue_empty.connect(self._hide_if_idle)
        self.signals.queue_updated.connect(self._on_queue_updated)
        self.signals.warning_message.connect(self.show_status)
        self.signals.post_action_ready.connect(self._queue_or_run_post_action)
        
        self.setWindowTitle(config.APP_NAME)
        
        flags = QtCore.Qt.WindowType.WindowTitleHint | QtCore.Qt.WindowType.CustomizeWindowHint | QtCore.Qt.WindowType.WindowCloseButtonHint
        flags |= QtCore.Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
        
        self._real_close = False
        
        self.base_width = 860
        self.base_height = 580
        self.setMinimumSize(self.base_width, self.base_height)
        
        self._internal_warned = False
        self.filepath: Optional[Path] = None
        self._bulk_subfolder_name: Optional[str] = None
        
        self._hide_secure = False
        self._post_action_mode = "none"
        self._pending_post_actions = {}
        self._batch_post_action_counter = 0
        self._batch_post_action_batches = {}
        self._post_action_consumed = False
        self._gallery_notification_targets: dict[str, set[str]] = {}
        self._load_config()       
        self._setup_server()
        
        self._build_ui()
        self._pending_dialog = PendingDialog(self.loc, self._bring_and_center)
        self._pending_dialog.set_pending_count(self.state_manager.pending_count())
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
        
        self.btn_lang = QPushButton(self.loc.get("lang_toggle"))
        self.btn_lang.setFixedWidth(40)
        self.btn_lang.setFixedHeight(25)
        self.btn_lang.clicked.connect(self._on_lang_toggle)
        
        self.btn_undo = QPushButton(self.loc.get("btn_history"))
        self.btn_undo.setFixedHeight(25)
        self.btn_undo.clicked.connect(self._on_undo_clicked)
        
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
        
        header_layout.addWidget(self.btn_lang)
        header_layout.addWidget(self.btn_undo)
        header_layout.addStretch()
        header_layout.addWidget(self.hide_secure_cb)
        header_layout.addWidget(self.blur_spinbox)
        header_layout.addWidget(self.chk_auto_run_pendings)
        header_layout.addWidget(self.time_auto_run_pendings)
        
        main_vbox.addLayout(header_layout)

        # CENTRO
        root = QHBoxLayout()
        
        # Selection Panel
        self.selection_panel = SelectionPanel(plugin_mgr=self.plugin_mgr)
        self.selection_panel.subfolder_clicked.connect(self._move_to_subfolder)
        self.selection_panel.copy_to_subfolder_clicked.connect(
            self._copy_selected_queue_files_to_subfolder
        )
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
        self.action_panel.action_toolbar.reload_clicked.connect(self._on_reload_clicked)
        root.addWidget(self.action_panel)

        # Queue / Character Panel
        self.queue_panel = QueuePanel()
        self.queue_panel.set_hide_secure(self._hide_secure)
        self.queue_panel.characters_updated.connect(self._update_character_buttons)
        self.queue_panel.character_updated.connect(self._on_single_character_updated)
        self.queue_panel.file_double_clicked.connect(self._on_queue_file_double_clicked)
        self.queue_panel.queue_file_rename_requested.connect(self._on_queue_file_rename_requested)
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
        while self._server.hasPendingConnections():
            client_socket = self._server.nextPendingConnection()
            client_socket.setProperty("command_buffer", b"")
            client_socket.readyRead.connect(
                lambda s=client_socket: self._read_server_data(s)
            )
            # Older clients sent a JSON object without a newline and closed the
            # connection immediately. Process that payload on disconnect too.
            client_socket.disconnected.connect(
                lambda s=client_socket: self._read_server_data(s, final=True)
            )
            client_socket.disconnected.connect(client_socket.deleteLater)

    def _read_server_data(self, socket, final: bool = False):
        try:
            if socket.property("command_processed"):
                return

            buffered = socket.property("command_buffer") or b""
            data = bytes(buffered) + socket.readAll().data()

            if b"\n" not in data and not final:
                socket.setProperty("command_buffer", data)
                return

            request_line = data.split(b"\n", 1)[0].strip()
            if not request_line:
                return

            socket.setProperty("command_buffer", b"")
            socket.setProperty("command_processed", True)

            try:
                command = json.loads(request_line.decode("utf-8"))
                response = self._handle_server_command(command)
            except (UnicodeDecodeError, json.JSONDecodeError):
                response = {
                    "ok": False,
                    "error": "invalid_json",
                    "message": "Request must be one UTF-8 JSON object followed by a newline.",
                }
            except Exception:
                logging.exception("Failed to process server command")
                response = {
                    "ok": False,
                    "error": "internal_error",
                    "message": "CatchEtude could not process the command.",
                }

            # New clients keep the socket open until they receive this response.
            # Legacy clients have already disconnected, but their request is still
            # processed through the final=True path above.
            if not final and socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
                payload = (json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8")
                socket.write(payload)
                socket.flush()
                socket.disconnectFromServer()
        except Exception:
            logging.exception("Failed while reading command endpoint data")
            if not final:
                socket.disconnectFromServer()

    def _handle_server_command(self, command: dict) -> dict:
        if not isinstance(command, dict):
            return {"ok": False, "error": "invalid_request", "message": "Expected a JSON object."}

        command_name = command.get("cmd")
        if command_name == "capture_ui_render":
            self._capture_ui_render()
            return {"ok": True, "command": "capture_ui_render"}

        # Requests without "cmd" are accepted for compatibility with older
        # send_command.py clients, which only supplied "path" and "hide_secure".
        if command_name not in (None, "enqueue_path"):
            return {
                "ok": False,
                "error": "unknown_command",
                "message": f"Unsupported command: {command_name}",
            }

        raw_path = command.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            return {"ok": False, "error": "missing_path", "message": "A non-empty path is required."}

        try:
            target = Path(raw_path).expanduser()
            if not target.exists():
                return {"ok": False, "error": "path_not_found", "message": f"Path does not exist: {raw_path}"}
            target = target.resolve()
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": "invalid_path", "message": str(exc)}

        if not target.is_file() and not target.is_dir():
            return {
                "ok": False,
                "error": "unsupported_path",
                "message": "The path must refer to an existing file or directory.",
            }
        if target.is_file() and is_temporary(target):
            return {
                "ok": False,
                "error": "temporary_file",
                "message": "Temporary files cannot be added to the pending queue.",
            }

        hide_secure = command.get("hide_secure", True)
        if not isinstance(hide_secure, bool):
            return {
                "ok": False,
                "error": "invalid_hide_secure",
                "message": "hide_secure must be a boolean.",
            }

        notify_server = command.get("notify_server")
        if notify_server is not None:
            valid_server_name = (
                isinstance(notify_server, str)
                and 1 <= len(notify_server) <= 128
                and all(
                    char.isalnum() or char in "._-"
                    for char in notify_server
                )
            )
            if not valid_server_name:
                return {
                    "ok": False,
                    "error": "invalid_notify_server",
                    "message": "notify_server must be a valid local socket name.",
                }

        self._hide_secure = hide_secure
        self.hide_secure_cb.setChecked(self._hide_secure)
        self.queue_panel.set_hide_secure(self._hide_secure)
        if hasattr(self, "action_panel") and self.action_panel is not None:
            self.action_panel._hide_secure = self._hide_secure
            self.action_panel.load_preview()
        self._save_config()

        if target.is_dir():
            self._process_pending_folder(target)
            kind = "folder"
        else:
            if notify_server:
                source_key = os.path.normcase(os.path.abspath(str(target)))
                self._gallery_notification_targets.setdefault(
                    source_key, set()
                ).add(notify_server)
                logging.info(
                    "Registered GalleryAnuary move notifications for %s via %s",
                    target,
                    notify_server,
                )
            self.state_manager.enqueue_file(target)
            kind = "file"

        logging.info("Accepted %s from command endpoint: %s", kind, target)
        return {
            "ok": True,
            "accepted": True,
            "kind": kind,
            "path": str(target),
        }

    def _notify_gallery_file_moved(self, src: Path, dst: Path) -> None:
        """Notifica a GalleryAnuary si registró el archivo original."""
        try:
            if not dst.exists() or src.exists():
                return

            source_key = os.path.normcase(os.path.abspath(str(src)))
            servers = self._gallery_notification_targets.pop(
                source_key, set()
            )
            if not servers:
                return

            source_folder = os.path.normcase(
                os.path.abspath(str(src.parent))
            )
            destination_folder = os.path.normcase(
                os.path.abspath(str(dst.parent))
            )
            if source_folder == destination_folder:
                return

            payload = (
                json.dumps(
                    {
                        "event": "file_moved",
                        "src": str(src),
                        "dst": str(dst),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            ).encode("utf-8")

            for server_name in servers:
                client = QLocalSocket(self)
                timeout = QtCore.QTimer(client)
                timeout.setSingleShot(True)
                timeout.timeout.connect(client.abort)
                client.connected.connect(
                    lambda sock=client, data=payload:
                    self._send_gallery_move_event(sock, data)
                )
                client.bytesWritten.connect(
                    lambda _count, sock=client:
                    sock.disconnectFromServer()
                    if sock.bytesToWrite() == 0
                    else None
                )
                client.disconnected.connect(timeout.stop)
                client.disconnected.connect(client.deleteLater)
                client.errorOccurred.connect(
                    lambda error, sock=client, endpoint=server_name:
                    self._on_gallery_notification_error(
                        sock, endpoint, error
                    )
                )
                timeout.start(2500)
                client.connectToServer(server_name)
        except Exception:
            logging.exception(
                "Could not notify GalleryAnuary about moved file %s -> %s",
                src,
                dst,
            )

    @staticmethod
    def _send_gallery_move_event(socket, payload: bytes) -> None:
        if socket.write(payload) < 0:
            logging.warning(
                "GalleryAnuary move event could not be queued: %s",
                socket.errorString(),
            )
            socket.abort()
            socket.deleteLater()
            return
        socket.flush()

    @staticmethod
    def _on_gallery_notification_error(socket, endpoint: str, error) -> None:
        logging.warning(
            "GalleryAnuary notification endpoint %s is unavailable: %s",
            endpoint,
            socket.errorString(),
        )
        socket.abort()
        socket.deleteLater()

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
        self.hide_secure_cb.setText(self.loc.get("btn_secure"))
        self.chk_auto_run_pendings.setText("Shedule Pendings")
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

        active_source = self.filepath
        selected_sources = self.queue_panel.get_selected_paths()
        if active_source not in selected_sources:
            selected_sources.insert(0, active_source)

        discarded_sources = []
        deleted_count = 0
        missing_count = 0
        failed_sources = []

        send_character_service_command("pause")
        try:
            for source in dict.fromkeys(selected_sources):
                if source.is_dir():
                    continue

                if not source.exists():
                    discarded_sources.append(source)
                    missing_count += 1
                    continue

                if delete_to_recycle_bin(source):
                    discarded_sources.append(source)
                    deleted_count += 1
                else:
                    failed_sources.append(source)

            if not discarded_sources:
                self.show_status("No se pudo eliminar ningún archivo seleccionado.", 5000)
                return

            active_removed = active_source in discarded_sources
            if active_removed:
                self.filepath = None
                self.action_panel.clear()
                self.queue_panel.set_progress(0)

            self.state_manager.discard_queued_files(discarded_sources)

            status_parts = []
            if deleted_count:
                status_parts.append(f"Eliminados {deleted_count} archivo(s) de la cola.")
            if missing_count:
                status_parts.append(
                    f"Se retiraron {missing_count} archivo(s) que ya no existían."
                )
            if failed_sources:
                status_parts.append(
                    f"No se pudieron eliminar {len(failed_sources)} archivo(s)."
                )
            self.show_status(" ".join(status_parts), 6000)

        finally:
            send_character_service_command("resume")

    def _start_undo(self, *, select_first: bool = False, show_dialog: bool = True):
        if self.background_move_mgr.undo_in_progress:
            return

        self._undo_select_first_after_finish = select_first
        send_character_service_command("pause")
        if not self.background_move_mgr.start_undo_last_move():
            send_character_service_command("resume")
            self._undo_select_first_after_finish = False
            if show_dialog:
                QtWidgets.QMessageBox.information(
                    self, "Undo", self.loc.get("msg_nothing_to_undo")
                )
            else:
                self.show_status(self.loc.get("msg_nothing_to_undo"), 5000)

    def _on_undo_clicked(self):
        self._start_undo(show_dialog=True)

    def _on_context_undo_clicked(self):
        self._start_undo(show_dialog=False)

    def _on_tray_undo_clicked(self):
        self._start_undo(select_first=True, show_dialog=True)

    @QtCore.pyqtSlot(str, int)
    def _on_undo_started(self, source_path: str, total_bytes: int):
        progress = QtWidgets.QProgressDialog(
            f"Deshaciendo archivo: {Path(source_path).name}", "", 0, 100, self
        )
        progress.setWindowTitle("Deshacer movimiento")
        progress.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        self._undo_progress_dialog = progress
        self.btn_undo.setEnabled(False)
        progress.show()

    @QtCore.pyqtSlot(int)
    def _on_undo_progress(self, value: int):
        if self._undo_progress_dialog is not None:
            self._undo_progress_dialog.setValue(max(0, min(100, int(value))))

    @QtCore.pyqtSlot(bool, str, str)
    def _on_undo_finished(self, success: bool, target_path: str, message: str):
        if self._undo_progress_dialog is not None:
            self._undo_progress_dialog.close()
            self._undo_progress_dialog.deleteLater()
            self._undo_progress_dialog = None

        send_character_service_command("resume")
        self.btn_undo.setEnabled(True)

        if success:
            if self._undo_select_first_after_finish:
                with self.state_manager._lock:
                    queue_list = list(self.state_manager._queue_list)
                if queue_list:
                    self.state_manager.select_queued_file(queue_list[0])

            self._build_tray()
            self._update_undo_button_tooltip()
            self._bring_and_center()

            if message == "TIMESTAMP_RESTORE_FAILED":
                self.show_status(
                    "El archivo se deshizo, pero no se pudieron restaurar sus fechas.",
                    8000,
                )
        else:
            self._update_undo_button_tooltip()
            if message == "TIMESTAMP_RESTORE_FAILED":
                self.show_status(
                    "No se pudo restaurar la fecha. La copia parcial se retiró y "
                    "el historial se conservó para permitir otro intento.",
                    8000,
                )
            else:
                self.show_status(
                    f"No se pudo deshacer el movimiento: {message}",
                    8000,
                )

        self._undo_select_first_after_finish = False

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
        if self._flatten_operation is not None or not self.background_move_mgr.is_idle():
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
            self._real_close = True
            QApplication.quit()

    def closeEvent(self, event):
        if not self._real_close:
            event.ignore()
            self._manual_hide()
            return

        if self._flatten_operation is not None or not self.background_move_mgr.is_idle():
            logging.warning("Close event blocked: active background file moves are in progress.")
            QtWidgets.QMessageBox.warning(
                self,
                self.loc.get("msg_cannot_close_moving_title") or "Operación en progreso",
                self.loc.get("msg_cannot_close_moving") or "No se puede cerrar la aplicación mientras se realiza un movimiento de archivos. Por favor, espere a que termine."
            )
            self._real_close = False
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
            self._pending_dialog.set_pending_count(self.state_manager.pending_count())
            self._pending_dialog.show()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_tray_show_hide_action()
        if hasattr(self, "selection_panel") and self.selection_panel:
            self.selection_panel.set_subfolders_enabled(True)

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
    
    
    def _add_collision_image_preview(self, box: QMessageBox, candidate: Path) -> None:
        """Adds a thumbnail of the existing destination file, never the source file."""
        if not candidate.is_file():
            return

        try:
            reader = QtGui.QImageReader(str(candidate))
            reader.setAutoTransform(True)
            preview_size = reader.size()
            if not preview_size.isValid():
                return

            preview_size.scale(360, 240, Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(preview_size)
            image = reader.read()
            if image.isNull():
                return

            preview = QtWidgets.QLabel(box)
            preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
            preview.setPixmap(QtGui.QPixmap.fromImage(image))
            preview.setToolTip(f"Archivo existente: {candidate.name}")
            preview.setAccessibleName(f"Vista previa del archivo existente {candidate.name}")

            layout = box.layout()
            if isinstance(layout, QtWidgets.QGridLayout):
                layout.addWidget(preview, layout.rowCount(), 0, 1, max(1, layout.columnCount()))
            else:
                layout.addWidget(preview)
        except Exception:
            logging.exception("Could not load duplicate destination preview: %s", candidate)

    def _start_duplicate_delete(self, candidate: Path, on_success: Callable[[], None]) -> bool:
        """Moves an existing duplicate to the Recycle Bin without blocking the UI thread."""
        operation_id = self._duplicate_delete_operation_counter
        self._duplicate_delete_operation_counter += 1

        progress = QtWidgets.QProgressDialog(
            f"Eliminando el archivo duplicado:\n{candidate.name}", "", 0, 0, self
        )
        progress.setWindowTitle("Eliminando duplicado")
        progress.setWindowModality(QtCore.Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)

        worker = _DuplicateDeleteWorker(operation_id, candidate)
        worker.signals.finished.connect(self._on_duplicate_delete_finished)
        self._duplicate_delete_operations[operation_id] = {
            "worker": worker,
            "progress": progress,
            "candidate": candidate,
            "on_success": on_success,
        }

        progress.show()
        try:
            QtCore.QThreadPool.globalInstance().start(worker)
        except Exception:
            self._duplicate_delete_operations.pop(operation_id, None)
            progress.close()
            progress.deleteLater()
            logging.exception("Could not start background deletion for duplicate: %s", candidate)
            self._show_warning_message(f"No se pudo eliminar el archivo existente:\n{candidate.name}")
            self.selection_panel.set_subfolders_enabled(True)
            return False

        return True

    @QtCore.pyqtSlot(int, str, bool)
    def _on_duplicate_delete_finished(self, operation_id: int, path_str: str, success: bool) -> None:
        operation = self._duplicate_delete_operations.pop(operation_id, None)
        if operation is None:
            return

        progress = operation["progress"]
        progress.close()
        progress.deleteLater()

        candidate = Path(path_str)
        if not success and candidate.exists():
            self._show_warning_message(f"No se pudo eliminar el archivo existente:\n{candidate.name}")
            self.selection_panel.set_subfolders_enabled(True)
            return

        try:
            operation["on_success"]()
        except Exception:
            logging.exception("Could not continue move after deleting duplicate: %s", candidate)
            self.selection_panel.set_subfolders_enabled(True)
            self._show_warning_message("El duplicado se eliminó, pero no se pudo continuar con el movimiento.")

    def _check_destination_collision(
        self,
        candidate: Path,
        allow_retry: bool = False,
        on_delete_complete: Optional[Callable[[], None]] = None,
    ) -> tuple[str, Optional[Path]]:
        if not candidate.exists():
            return "move", candidate

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Archivo con el mismo nombre")
        box.setText(f"Ya existe un archivo con el mismo nombre:\n{candidate.name}")
        box.setInformativeText("Elige qué hacer.")
        self._add_collision_image_preview(box, candidate)

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
            if on_delete_complete is None:
                logging.error("Duplicate deletion requested without a move continuation: %s", candidate)
                self.selection_panel.set_subfolders_enabled(True)
                return "cancel", None
            if self._start_duplicate_delete(candidate, on_delete_complete):
                return "pending", None
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
        run_in_threadpool(self.state_manager._run_maintenance_scan)

    def _on_order_one_pending_clicked(self):
        selected_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select File to Process",
            str(config.DOWNLOADS),
            "All Files (*)",
        )
        if not selected_file:
            return

        path = Path(selected_file)
        if not path.is_file():
            self.show_status("El archivo seleccionado ya no existe o no es válido.", 5000)
            return
        if is_temporary(path):
            self.show_status("No se pueden ordenar archivos temporales.", 5000)
            return

        self.state_manager.enqueue_file(path)

    def _on_order_pending_clicked(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Process", str(config.DOWNLOADS))
        if folder: self._process_pending_folder(Path(folder))

    def _run_pendings(self):
        CREATE_NO_WINDOW = 0x08000000
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        try:
            pendings_script = str(Path(__file__).resolve().parent / "pendings_exec.pyw")
            python_exe = sys.executable
            
            if python_exe.lower().endswith("python.exe"):
                python_exe = python_exe[:-10] + "pythonw.exe"
                
            subprocess.Popen([python_exe, pendings_script], creationflags=flags)
        except Exception:
            logging.exception("Failed to run pendings script")
    
    def _run_download_cmd_builder(self):
        CREATE_NO_WINDOW = 0x08000000
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        try:
            pendings_script = str(Path(__file__).resolve().parent / "cmd_builder.py")
            python_exe = sys.executable
            
            if python_exe.lower().endswith("python.exe"):
                python_exe = python_exe[:-10] + "pythonw.exe"
            
            subprocess.Popen([python_exe, pendings_script], creationflags=flags)
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

    def _start_flatten_operation(self, folder: Path, on_finished: Callable):
        if self._flatten_operation is not None:
            self.show_status("Ya hay una operación de aplanado en curso.", 5000)
            return False

        signals = _FlattenOperationSignals(self)
        dialog = QtWidgets.QProgressDialog(
            f"Buscando archivos en {folder.name}...", "", 0, 0, self
        )
        dialog.setWindowTitle("Aplanar carpeta")
        dialog.setWindowModality(QtCore.Qt.WindowModality.WindowModal)
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)

        self._flatten_operation = {
            "folder": folder,
            "signals": signals,
            "dialog": dialog,
            "on_finished": on_finished,
        }
        signals.progress.connect(self._on_flatten_progress)
        signals.finished.connect(self._on_flatten_finished)
        dialog.show()

        def worker():
            try:
                moved, success = flatten_single_folder(
                    folder,
                    progress_callback=lambda current, total, path, phase:
                        signals.progress.emit(current, total, path, phase),
                )
                signals.finished.emit(moved, success, "")
            except Exception as exc:
                logging.exception("Flatten operation failed for %s", folder)
                signals.finished.emit([], False, str(exc))

        run_in_threadpool(worker)
        return True

    @QtCore.pyqtSlot(int, int, str, str)
    def _on_flatten_progress(
        self, completed: int, total: int, current_path: str, phase: str
    ):
        operation = self._flatten_operation
        if operation is None:
            return

        dialog = operation["dialog"]
        folder = operation["folder"]
        if phase == "scan":
            dialog.setRange(0, 0)
            dialog.setLabelText(f"Buscando archivos en {folder.name}...")
            return

        maximum = max(1, int(total))
        dialog.setRange(0, maximum)
        dialog.setValue(max(0, min(int(completed), maximum)))
        if current_path:
            dialog.setLabelText(
                f"Aplanando {folder.name}\n{Path(current_path).name} "
                f"({completed}/{total})"
            )
        elif phase == "finished":
            dialog.setLabelText(f"Finalizando {folder.name}...")
        else:
            dialog.setLabelText(f"Aplanando {folder.name} ({completed}/{total})...")

    @QtCore.pyqtSlot(object, bool, str)
    def _on_flatten_finished(self, moved, success: bool, error: str):
        operation = self._flatten_operation
        if operation is None:
            return

        self._flatten_operation = None
        dialog = operation["dialog"]
        dialog.close()
        dialog.deleteLater()

        moved_paths = [Path(path) for path in (moved or [])]
        if moved_paths:
            self.state_manager.enqueue_files(moved_paths)

        operation["on_finished"](moved_paths, bool(success), str(error or ""))

    def _set_ui_enabled_for_move(self, enabled: bool):
        if self.filepath and self.filepath.is_dir():
            self.action_panel.action_toolbar.action_delete.setEnabled(False)
            self.action_panel.rename_input.setEnabled(False)
            self.selection_panel.setEnabled(False)
            return

        self.selection_panel.setEnabled(True)
        self.action_panel.action_toolbar.action_delete.setEnabled(enabled and bool(self.filepath))
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

                def on_autoflat_finish(moved, success, error):
                    if success:
                        self.action_panel.clear()
                        self.filepath = None
                        self.state_manager.discard_active_file()
                    else:
                        self._set_ui_enabled_for_move(True)
                        detail = f" ({error})" if error else ""
                        self.show_status(
                            f"Auto-flat falló para {folder.name}{detail}. "
                            "Por favor, hágalo manualmente.",
                            8000,
                        )

                self._start_flatten_operation(folder, on_autoflat_finish)
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
            self.loc.get("save_all_another_folder"),
            self.loc.get("save_all_another_folder_open_folder"),
            "Save all files in another folder",
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

        elif action_name in (
            self.loc.get("save_all_another_folder"),
            self.loc.get("save_all_another_folder_open_folder"),
            "Save all files in another folder",
            "Save all file in another folder and open folder",
        ):
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

        action, final_dest = self._check_destination_collision(
            candidate,
            on_delete_complete=lambda: self._start_move_task(decision, candidate),
        )
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
        if not p.is_file():
            return
        # A folder may be the active queue item. Double-clicking a file must
        # still allow the user to switch the active queue entry to that file.
        self.state_manager.select_queued_file(p)

    def _on_queue_file_rename_requested(self, path_str: str):
        """Rename a queued file and let the watcher re-enqueue it at its former index."""
        source = Path(path_str)
        if not source.is_file():
            self.show_status(self.loc.get("msg_queue_rename_missing"), 5000)
            return

        dialog = QueueRenameDialog(source, self.loc, self)
        if dialog.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        new_stem = dialog.new_stem
        if not new_stem:
            return

        destination = source.with_name(f"{new_stem}{source.suffix}")
        source_key = os.path.normcase(os.path.abspath(str(source))).casefold()
        destination_key = os.path.normcase(os.path.abspath(str(destination))).casefold()
        if source_key == destination_key:
            return

        if destination.exists():
            self.show_status(
                self.loc.get("msg_queue_rename_exists").format(name=destination.name),
                6000,
            )
            return

        try:
            renamed = self.state_manager.rename_queued_file(source, destination)
        except FileExistsError:
            self.show_status(
                self.loc.get("msg_queue_rename_exists").format(name=destination.name),
                6000,
            )
            return
        except Exception as exc:
            logging.exception("Could not rename queued file %s", source)
            self.show_status(
                self.loc.get("msg_queue_rename_failed").format(error=exc),
                7000,
            )
            return

        if not renamed:
            self.show_status(self.loc.get("msg_queue_rename_not_queued"), 6000)
            return

        # Ask the same stability watcher used by filesystem events to rediscover
        # the renamed path. It also accepts explicit candidates in Downloads subfolders.
        try:
            downloads_root = Path(config.DOWNLOADS).resolve()
            resolved_destination = destination.resolve()
            is_inside_downloads = (
                resolved_destination != downloads_root
                and downloads_root in resolved_destination.parents
            )
        except OSError:
            is_inside_downloads = False

        watcher_candidate = getattr(self.state_manager, "recent_path_handler", None)
        try:
            if is_inside_downloads and callable(watcher_candidate):
                watcher_candidate(destination)
            else:
                # Queue entries may originate outside Downloads; keep them queued
                # even though the Downloads watcher does not monitor those paths.
                self.state_manager.enqueue_file(destination)
        except Exception:
            logging.exception("Could not schedule renamed queue file for rediscovery: %s", destination)
            self.state_manager.enqueue_file(destination)

        self.show_status(self.loc.get("msg_queue_rename_scanning"), 6000)

    @QtCore.pyqtSlot(list, str)
    def _on_queue_updated(self, queue_list: list[Path], active_path_str: str):
        self.queue_panel.update_queue(queue_list, active_path_str)
        if hasattr(self, "_pending_dialog"):
            self._pending_dialog.set_pending_count(self.state_manager.pending_count())
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
        # Character subfolder buttons intentionally use two lines: name and summary.
        self.selection_panel.update_subfolder_button(folder_name, line2, "")

    def _update_character_buttons(self):
        t = self.selection_panel.get_selection()['type']
        if t != 2: return
            
        for c in self.queue_panel.get_characters():
            self._on_single_character_updated(c)

    def _register_batch_post_action(
        self, target: Path, post_action: str, task_count: int
    ) -> int | None:
        """Register a single post-action to run when a batch's moves have all finished."""
        if post_action != "open_folder" or task_count <= 0:
            return None

        self._batch_post_action_counter += 1
        batch_id = self._batch_post_action_counter
        self._batch_post_action_batches[batch_id] = {
            "target": Path(target),
            "remaining": task_count,
        }
        return batch_id

    def _complete_batch_post_action(self, batch_id: int | None) -> None:
        """Open a batch destination once, after every move in the batch has reported."""
        if batch_id is None:
            return

        batch = self._batch_post_action_batches.get(batch_id)
        if batch is None:
            return

        batch["remaining"] -= 1
        if batch["remaining"] > 0:
            return

        self._batch_post_action_batches.pop(batch_id, None)
        self._run_post_action(batch["target"], "open_folder")

    def _keep_all_queued_files(self, post_action: str = "none"):
        """Queue a keep operation for every file currently in the download queue."""
        sources = self.state_manager.start_all_background_moves()
        if not sources:
            self.show_status("No hay archivos en cola para conservar.", 5000)
            return

        tasks = []
        skipped_sources = []
        reserved_destinations = set()
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

            destination = self._check_batch_destination_collision(config.CONFLICTS / source.name)
            if destination is None:
                skipped_sources.append(source)
                continue
            suffix_index = 1
            base_destination = destination
            while destination.exists() or destination in reserved_destinations:
                destination = base_destination.with_name(
                    f"{base_destination.stem}_{suffix_index}{base_destination.suffix}"
                )
                suffix_index += 1
            reserved_destinations.add(destination)
            tasks.append((source, destination, source_meta))

        if not tasks:
            self.filepath = None
            self.action_panel.clear()
            for source in reversed(skipped_sources):
                self.state_manager.fail_background_move(source)
            self.show_status("No se pudieron preparar archivos para conservar.", 5000)
            return

        batch_post_action_id = self._register_batch_post_action(
            config.CONFLICTS, post_action, len(tasks)
        )
        send_character_service_command("pause")
        for source, destination, source_meta in tasks:
            decision = {
                "action": "keep",
                "new_name": source.stem,
                "post_action": "none" if batch_post_action_id is not None else post_action,
                "_batch_post_action_id": batch_post_action_id,
            }
            self.background_move_mgr.enqueue_move(
                source, destination, decision, source_meta
            )

        self.filepath = None
        self.action_panel.clear()
        for source in reversed(skipped_sources):
            self.state_manager.fail_background_move(source)
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
        skipped_sources = []
        reserved_destinations = set()
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

            destination = self._check_batch_destination_collision(dest_dir / source.name)
            if destination is None:
                skipped_sources.append(source)
                continue
            suffix_index = 1
            base_destination = destination
            while destination.exists() or destination in reserved_destinations:
                destination = base_destination.with_name(
                    f"{base_destination.stem}_{suffix_index}{base_destination.suffix}"
                )
                suffix_index += 1
            reserved_destinations.add(destination)
            tasks.append((source, destination, source_meta))

        if not tasks:
            self.filepath = None
            self.action_panel.clear()
            for source in reversed(skipped_sources):
                self.state_manager.fail_background_move(source)
            self.show_status("No se pudieron preparar archivos para guardar.", 5000)
            return

        batch_post_action_id = self._register_batch_post_action(
            dest_dir, post_action, len(tasks)
        )
        send_character_service_command("pause")
        for source, destination, source_meta in tasks:
            decision = {
                "action": "move_custom",
                "custom_dir": str(dest_dir),
                "new_name": source.stem,
                "post_action": "none" if batch_post_action_id is not None else post_action,
                "_batch_post_action_id": batch_post_action_id,
            }
            self.background_move_mgr.enqueue_move(
                source, destination, decision, source_meta
            )

        self.filepath = None
        self.action_panel.clear()
        for source in reversed(skipped_sources):
            self.state_manager.fail_background_move(source)
        self.show_status(f"Guardando {len(tasks)} archivos en {dest_dir.name}.", 5000)

    def _copy_selected_queue_files_to_subfolder(self, target_folder_path: str):
        """Copy the active file and any other selected queue entries to a subfolder."""
        if not self.filepath or self.filepath.is_dir():
            return

        target_folder = Path(target_folder_path)
        if not target_folder.is_dir():
            self.show_status("La carpeta de destino ya no existe.", 5000)
            return

        selected_sources = self.queue_panel.get_selected_paths()
        if self.filepath not in selected_sources:
            selected_sources.insert(0, self.filepath)

        valid_sources = []
        destination_map = {}
        reserved_destinations = set()
        skipped_count = 0
        for source in dict.fromkeys(selected_sources):
            try:
                if not source.is_file() or is_file_locked(source):
                    skipped_count += 1
                    continue
            except OSError:
                skipped_count += 1
                continue

            destination = self._check_batch_destination_collision(target_folder / source.name)
            if destination is None:
                skipped_count += 1
                continue

            suffix_index = 1
            base_destination = destination
            while destination.exists() or destination in reserved_destinations:
                destination = base_destination.with_name(
                    f"{base_destination.stem}_{suffix_index}{base_destination.suffix}"
                )
                suffix_index += 1
            reserved_destinations.add(destination)
            destination_map[source] = destination
            valid_sources.append(source)

        if not valid_sources:
            self.show_status("No hay archivos seleccionados disponibles para copiar.", 5000)
            return

        operation_id = self._queue_copy_operation_counter
        self._queue_copy_operation_counter += 1

        worker = _QueueFileCopyWorker(
            operation_id, target_folder, valid_sources, destinations=destination_map
        )
        worker.signals.finished.connect(self._on_queue_file_copy_finished)
        self._queue_copy_operations[operation_id] = {
            "worker": worker,
            "target_name": target_folder.name,
            "skipped_count": skipped_count,
        }
        QtCore.QThreadPool.globalInstance().start(worker)

        self.show_status(
            f"Copiando {len(valid_sources)} archivo(s) a {target_folder.name}.",
            5000,
        )

    @QtCore.pyqtSlot(int, object, object)
    def _on_queue_file_copy_finished(self, operation_id: int, copied, failed):
        operation = self._queue_copy_operations.pop(operation_id, None)
        if operation is None:
            return

        copied_count = len(copied)
        skipped_count = operation["skipped_count"] + len(failed)
        status_parts = []
        if copied_count:
            status_parts.append(
                f"Copiados {copied_count} archivo(s) en {operation['target_name']}."
            )
        if skipped_count:
            status_parts.append(f"No se pudieron copiar {skipped_count} archivo(s).")
        if not status_parts:
            status_parts.append("No se pudo copiar ningún archivo.")
        self.show_status(" ".join(status_parts), 6000)

    def _move_to_subfolder(self, sub_name: str, post_action: str = "none"):
        if not self.filepath or self.filepath.is_dir():
            return

        selected_sources = self.queue_panel.get_selected_paths()
        if self.filepath not in selected_sources:
            selected_sources.insert(0, self.filepath)

        self.selection_panel.set_subfolders_enabled(False)
        if len(set(selected_sources)) > 1:
            self._move_selected_queue_files_to_subfolder(
                sub_name, selected_sources, post_action=post_action
            )
            return

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
        action, final_dest = self._check_destination_collision(
            candidate,
            on_delete_complete=lambda: self._start_move_task(decision, candidate),
        )
        if action == "pending":
            return
        if action != "move" or final_dest is None:
            self.selection_panel.set_subfolders_enabled(True)
            return
        self._start_move_task(decision, final_dest)

    def _check_batch_destination_collision(self, candidate: Path) -> Optional[Path]:
        """Ask before scheduling a batch item whose name already exists in its folder."""
        candidate = Path(candidate)
        if not candidate.exists():
            return candidate

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Archivo duplicado en la carpeta")
        box.setText(
            f"Ya existe un archivo con el mismo nombre en esta carpeta:\n"
            f"{candidate.parent}\n\n{candidate.name}"
        )
        box.setInformativeText(
            "Puedes conservar ambos archivos con otro nombre, abrir el existente "
            "u omitir este archivo."
        )
        btn_rename = box.addButton(
            "Guardar con otro nombre", QMessageBox.ButtonRole.AcceptRole
        )
        btn_open = box.addButton(
            "Abrir existente", QMessageBox.ButtonRole.ActionRole
        )
        box.addButton("Omitir archivo", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(btn_rename)
        box.exec()

        clicked = box.clickedButton()
        if clicked == btn_rename:
            return resolve_duplicate(candidate)
        if clicked == btn_open:
            try:
                os.startfile(str(candidate))
            except OSError as exc:
                self.show_status(f"No se pudo abrir el archivo existente: {exc}", 5000)
        return None

    def _move_selected_queue_files_to_subfolder(
        self, sub_name: str, selected_sources: list[Path], post_action: str = "none"
    ):
        """Move selected queue entries to a classification subfolder in parallel."""
        active_source = self.filepath
        sel = self.selection_panel.get_selection()
        prepared = []
        reserved_destinations = set()

        for source in dict.fromkeys(selected_sources):
            if not source.exists() or source.is_dir():
                continue

            if is_file_locked(source):
                if source == active_source:
                    self.show_status(self.loc.get("msg_file_locked"), 5000)
                    self.selection_panel.set_subfolders_enabled(True)
                    return
                logging.warning("Skipping locked selected queue file: %s", source)
                continue

            try:
                source_stat = source.stat()
                source_meta = {
                    "atime": source_stat.st_atime,
                    "mtime": source_stat.st_mtime,
                    "ctime": getattr(source_stat, "st_birthtime", source_stat.st_ctime),
                }
                new_name = (
                    (self.action_panel.get_new_name() or source.stem)
                    if source == active_source else source.stem
                )
                decision = {
                    "action": "move",
                    "movement_type": sel["type"],
                    "year": sel["year"],
                    "sub": sub_name,
                    "new_name": new_name,
                    "post_action": post_action,
                }
                candidate = compute_destination(decision, source)
            except Exception:
                logging.exception("Could not prepare selected queue file for move: %s", source)
                if source == active_source:
                    self.selection_panel.set_subfolders_enabled(True)
                    self.show_status("No se pudo preparar el archivo activo para moverlo.", 5000)
                    return
                continue

            destination = self._check_batch_destination_collision(candidate)
            if destination is None:
                if source == active_source:
                    self.selection_panel.set_subfolders_enabled(True)
                    self.show_status(
                        "Movimiento cancelado: el archivo activo no se modificó.",
                        5000,
                    )
                    return
                logging.info("Skipping selected queue file after destination collision: %s", source)
                continue

            suffix_index = 1
            while destination.exists() or destination in reserved_destinations:
                destination = destination.with_name(
                    f"{destination.stem}_{suffix_index}{destination.suffix}"
                )
                suffix_index += 1
            reserved_destinations.add(destination)
            prepared.append({
                "source": source,
                "destination": destination,
                "decision": decision,
                "source_meta": source_meta,
            })

        if not prepared or active_source not in {task["source"] for task in prepared}:
            self.selection_panel.set_subfolders_enabled(True)
            self.show_status("No se pudieron preparar archivos seleccionados para mover.", 5000)
            return

        sources = self.state_manager.reserve_selected_background_moves(
            [task["source"] for task in prepared]
        )
        if not sources:
            self.selection_panel.set_subfolders_enabled(True)
            self.show_status("La cola cambió; no se movió ningún archivo seleccionado.", 5000)
            return

        reserved_sources = set(sources)
        move_tasks = [task for task in prepared if task["source"] in reserved_sources]
        batch_post_action_id = None
        if not self._bulk_subfolder_name and post_action == "open_folder" and move_tasks:
            batch_post_action_id = self._register_batch_post_action(
                move_tasks[0]["destination"].parent, post_action, len(move_tasks)
            )

        scheduled_count = 0
        try:
            for task in move_tasks:
                source = task["source"]
                decision = task["decision"]
                if batch_post_action_id is not None:
                    decision["post_action"] = "none"
                    decision["_batch_post_action_id"] = batch_post_action_id

                try:
                    self.background_move_mgr.enqueue_move(
                        source, task["destination"], decision, task["source_meta"]
                    )
                except Exception:
                    logging.exception("Could not enqueue selected queue move: %s", source)
                    self.state_manager.fail_background_move(source)
                    if batch_post_action_id is not None:
                        self._complete_batch_post_action(batch_post_action_id)
                    continue

                scheduled_count += 1
                try:
                    send_character_service_command("pause")
                except Exception:
                    logging.exception("Could not pause character service for selected move: %s", source)
        finally:
            self.filepath = None
            self.action_panel.clear()
            self.state_manager.finish_selected_background_moves()

        if scheduled_count:
            status = f"Moviendo {scheduled_count} archivo(s) a {sub_name}."
            skipped_count = len(selected_sources) - scheduled_count
            if skipped_count > 0:
                status += f" Se omitieron {skipped_count}."
            self.show_status(status, 5000)
        else:
            self.selection_panel.set_subfolders_enabled(True)
            self.show_status("No se pudieron iniciar los movimientos seleccionados.", 5000)

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
            action, final_dest = self._check_destination_collision(
                candidate,
                allow_retry=True,
                on_delete_complete=lambda: self._start_move_task(decision, candidate),
            )

            if action == "pending":
                return

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
            self._notify_gallery_file_moved(src, dst)
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
                self._notify_gallery_file_moved(src, dst)
                self._build_tray()
            elif msg == "FILE_LOCKED":
                self.show_status(self.loc.get("msg_file_locked"), 5000)
                self.state_manager.fail_background_move(src)
            else:
                self.state_manager.fail_background_move(src)

        self._hide_if_idle()
        self._complete_batch_post_action(decision.get("_batch_post_action_id"))

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

        def on_flat_finish(moved, success, error):
            if success:
                self.action_panel.clear()
                self.filepath = None
                self.state_manager.discard_active_file()
            else:
                self._set_ui_enabled_for_move(True)
                detail = f" ({error})" if error else ""
                self.show_status(f"Flat folder falló para {folder.name}{detail}.", 8000)

        self._start_flatten_operation(folder, on_flat_finish)

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
