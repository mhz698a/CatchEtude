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

from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QCompleter, QFileDialog,
    QHBoxLayout, QVBoxLayout, QSystemTrayIcon, QMenu
)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import Qt

from config import (
    APP_NAME, LOG_PATH, CRASH_REPORT_PATH,
    YEARS, ICON_PATH, CONFIG_PATH, MYAPPID, DOWNLOADS,
    BASE_INTERNAL, IMAGES_FOLDER, MUSIC_FOLDER,
)
from utils import (
    resolve_duplicate, flatten_downloads_root,
    configure_dwm_thumbnail_behavior, is_internal_available,
    sanitize_windows_filename, is_temporary,
    is_same_drive, move_file_shfileop, delete_to_recycle_bin
)
from state_manager import StateManager, State, scan_existing_downloads
from fallback_utils import compute_destination
from file_worker_mgr import FileMoveWorker
from app_signals_mgr import AppSignals
from localization import LocalizationManager

from selection_panel_mgr import SelectionPanel
from action_panel_mgr import ActionPanel
from queue_panel_mgr import QueuePanel
from service_mgr import send_character_service_command

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

        self._active_workers = set()

        self.signals.file_detected.connect(self.on_file_detected)
        self.signals.queue_empty.connect(self._hide_if_idle)
        self.signals.queue_updated.connect(self._on_queue_updated)

        self.setWindowTitle(APP_NAME)

        flags = QtCore.Qt.WindowType.WindowTitleHint | QtCore.Qt.WindowType.CustomizeWindowHint
        flags |= QtCore.Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)

        self.base_width = 820
        self.base_height = 580
        self.setMinimumSize(self.base_width, self.base_height)

        self._internal_warned = False
        self.filepath: Optional[Path] = None
        self._internal_available_at_start = is_internal_available()
        self._hide_secure = False
        self._load_config()

        self._setup_server()

        self._build_ui()
        self._build_tray()

        configure_dwm_thumbnail_behavior(self.winId().__int__())

        self._year_load_timer = QtCore.QTimer(self)
        self._year_load_timer.setSingleShot(True)
        self._year_load_timer.timeout.connect(self._load_characters_for_year)
        self._pending_year = None
        self._char_load_generation = 0

    def _build_ui(self):
        main_vbox = QVBoxLayout(self)

        # Header Row
        header_layout = QHBoxLayout()
        self.btn_delete_header = QPushButton(self.loc.get("btn_header_delete"))
        self.btn_delete_header.setFixedHeight(25)
        self.btn_delete_header.clicked.connect(self._on_delete_clicked)
        header_layout.addWidget(self.btn_delete_header)
        header_layout.addStretch()

        self.btn_undo = QPushButton(self.loc.get("btn_history"))
        self.btn_undo.setFixedHeight(25)
        self.btn_undo.clicked.connect(self._on_undo_clicked)

        self.btn_lang = QPushButton(self.loc.get("lang_toggle"))
        self.btn_lang.setFixedWidth(40)
        self.btn_lang.setFixedHeight(25)
        self.btn_lang.clicked.connect(self._on_lang_toggle)

        header_layout.addStretch()
        header_layout.addWidget(self.btn_undo)
        header_layout.addWidget(self.btn_lang)
        main_vbox.addLayout(header_layout)

        root = QHBoxLayout()

        # Selection Panel
        self.selection_panel = SelectionPanel()
        self.selection_panel.subfolder_clicked.connect(self._move_to_subfolder)
        self.selection_panel.type_changed.connect(self._on_type_changed)
        self.selection_panel.year_changed.connect(self._on_year_changed)
        root.addWidget(self.selection_panel)

        # Action Panel
        self.action_panel = ActionPanel()
        self.action_panel.apply_clicked.connect(self._on_move)
        self.action_panel.apply_custom_clicked.connect(self._on_apply_custom)
        self.action_panel.secure_changed.connect(self._on_secure_changed)
        root.addWidget(self.action_panel)

        # Queue / Character Panel
        self.queue_panel = QueuePanel()
        self.queue_panel.characters_updated.connect(self._update_character_buttons)
        root.addWidget(self.queue_panel)

        main_vbox.addLayout(root)
        self.retranslate_ui()

        # Initial size adjustment
        self.resize(self.base_width + self.queue_panel.width(), self.base_height)

    def _load_config(self):
        try:
            if CONFIG_PATH.exists():
                with CONFIG_PATH.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._hide_secure = data.get("hide_secure", False)
        except Exception:
            logging.exception("Failed to load config")

    def _save_config(self):
        try:
            data = {}
            if CONFIG_PATH.exists():
                with CONFIG_PATH.open('r', encoding='utf-8') as f:
                    data = json.load(f)
            data["hide_secure"] = self._hide_secure
            with CONFIG_PATH.open('w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
        except Exception:
            logging.exception("Failed to save config")

    def _on_secure_changed(self, hide_secure):
        self._hide_secure = hide_secure
        self._save_config()

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
            path = cmd.get("path")
            hide_secure = cmd.get("hide_secure", True)
            if path and os.path.exists(path):
                self._hide_secure = hide_secure
                self._save_config()
                p = Path(path)
                if p.is_dir():
                    self._process_pending_folder(p)
                else:
                    self.state_manager.enqueue_file(p)
        except Exception:
            logging.exception("Failed to process server command")
        socket.disconnectFromServer()

    def retranslate_ui(self):
        self.btn_delete_header.setText(self.loc.get("btn_header_delete"))
        self.btn_undo.setText(self.loc.get("btn_history"))
        self.btn_lang.setText(self.loc.get("lang_toggle"))
        self.selection_panel.retranslate_ui()
        self.action_panel.retranslate_ui()
        self.queue_panel.retranslate_ui()

    def _on_lang_toggle(self):
        self.loc.toggle_lang()
        self.retranslate_ui()
        self._build_tray()

    def _on_delete_clicked(self):
        if not self.filepath: return
        send_character_service_command("pause")
        try:
            if delete_to_recycle_bin(self.filepath):
                self.state_manager.discard_active_file()
                self.action_panel.set_progress(0)
            else:
                QtWidgets.QMessageBox.warning(self, "Error", "Could not delete file.")
        finally:
            send_character_service_command("resume")

    def _on_undo_clicked(self):
        send_character_service_command("pause")
        try:
            if not self.state_manager.undo_last_move():
                QtWidgets.QMessageBox.information(self, "Undo", "Nothing to undo or file no longer exists.")
        finally:
            send_character_service_command("resume")

    def _on_exit_clicked(self):
        reply = QtWidgets.QMessageBox.question(
            self, self.loc.get("msg_exit_title"), self.loc.get("msg_exit_confirm"),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            QApplication.quit()

    def _build_tray(self):
        icon = QIcon.fromTheme("folder-downloads")
        if icon.isNull(): icon = QIcon(ICON_PATH)
        if not hasattr(self, 'tray'):
            self.tray = QSystemTrayIcon(icon, self)
            self.tray.setToolTip(APP_NAME)
        self.tray_menu = QMenu(self)
        show_action = QAction(self.loc.get("tray_show"), self)
        show_action.triggered.connect(self.show)
        self.tray_menu.addAction(show_action)
        hide_action = QAction(self.loc.get("tray_hide"), self)
        hide_action.triggered.connect(self.hide)
        self.tray_menu.addAction(hide_action)
        rescan_action = QAction(self.loc.get("tray_rescan"), self)
        rescan_action.triggered.connect(self._rescan_downloads)
        self.tray_menu.addAction(rescan_action)
        order_pending_action = QAction(self.loc.get("tray_order_pending"), self)
        order_pending_action.triggered.connect(self._on_order_pending_clicked)
        self.tray_menu.addAction(order_pending_action)
        run_pendings_action = QAction(self.loc.get("tray_run_pendings"), self)
        run_pendings_action.triggered.connect(self._run_pendings)
        self.tray_menu.addAction(run_pendings_action)
        undo_action = QAction(self.loc.get("tray_undo"), self)
        undo_action.triggered.connect(self._on_undo_clicked)
        self.tray_menu.addAction(undo_action)
        center_action = QAction(self.loc.get("tray_center"), self)
        center_action.triggered.connect(self._bring_and_center)
        self.tray_menu.addAction(center_action)
        logs_action = QAction(self.loc.get("tray_logs"), self)
        logs_action.triggered.connect(self._show_logs)
        self.tray_menu.addAction(logs_action)
        restart_action = QAction(self.loc.get("tray_restart"), self)
        restart_action.triggered.connect(self._restart_service)
        self.tray_menu.addAction(restart_action)
        quit_action = QAction(self.loc.get("tray_exit"), self)
        quit_action.triggered.connect(self._on_exit_clicked)
        self.tray.setContextMenu(self.tray_menu)
        self.tray.show()

    def _show_logs(self):
        socket = QLocalSocket()
        socket.connectToServer("CatchEtudeLogServer")
        if socket.waitForConnected(100):
            data = json.dumps({"cmd": "show"})
            socket.write(data.encode('utf-8'))
            socket.waitForBytesWritten(100)
            socket.disconnectFromServer()

    def _bring_and_center(self):
        self.show()
        screen = self.screen().availableGeometry()
        size = self.geometry()
        x = (screen.width() - size.width()) // 2
        y = (screen.height() - size.height()) // 2
        self.move(x, y)
        self.raise_()
        self.activateWindow()

    def _restart_service(self):
        pid = os.getpid()
        script_path = str(Path(sys.argv[0]).resolve())
        restart_script = str(Path(__file__).resolve().parent / "restart_app.py")
        flags = 0x00000010
        try:
            subprocess.Popen([sys.executable, restart_script, str(pid), script_path], creationflags=flags)
        except Exception:
            subprocess.Popen([sys.executable, restart_script, str(pid), script_path])
        QApplication.quit()

    def _rescan_downloads(self):
        threading.Thread(target=lambda: scan_existing_downloads(self.state_manager), daemon=True).start()

    def _on_order_pending_clicked(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Process", str(DOWNLOADS))
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
            files = sorted(folder.rglob('*'))
            for f in files:
                if f.is_file() and not is_temporary(f):
                    self.state_manager.enqueue_file(f)
        threading.Thread(target=worker, daemon=True).start()

    @QtCore.pyqtSlot(str)
    def on_file_detected(self, path_str: str):
        p = Path(path_str)
        if not p.exists(): return
        if self.state_manager.current_state() != State.FILE_DETECTED: return
        if not self.state_manager.declare_user_deciding(): return

        self.filepath = p
        self.action_panel.set_file(p, self._hide_secure)
        self.action_panel.set_progress(0)

        # Sync panels
        sel = self.selection_panel.get_selection()
        self._on_type_changed(sel['type'])

        if not self.isVisible() and self._internal_available_at_start:
            self._bring_and_center()

        self._update_name_completer()

    def _on_type_changed(self, t: int):
        if t in (2, 3, 4, 7, 8) and not is_internal_available():
            if not self._internal_warned:
                self._internal_warned = True
                QtWidgets.QMessageBox.warning(self, "Almacenamiento no disponible", "El disco interno (E:\\_Internal) no está conectado.")
            self.selection_panel.list_sub.clear()
            self.selection_panel.list_sub.setEnabled(False)
            self.selection_panel.list_year.setEnabled(False)
            return

        self.action_panel.set_apply_enabled(t not in (2, 3, 4, 6, 8))
        self._update_name_completer()

    def _on_year_changed(self, year: int):
        t = self.selection_panel.get_selection()['type']
        if t == 2:
            self._pending_year = year
            self._year_load_timer.start(400)
        self._update_name_completer()

    def _load_characters_for_year(self):
        if self._pending_year is None: return
        self._char_load_generation += 1
        self.queue_panel.request_characters(self._pending_year, self._char_load_generation)

    @QtCore.pyqtSlot(list, str)
    def _on_queue_updated(self, queue_list: list[Path], active_path_str: str):
        self.queue_panel.update_queue(queue_list, active_path_str)

    def _update_character_buttons(self):
        t = self.selection_panel.get_selection()['type']
        if t != 2: return

        for c in self.queue_panel.get_characters():
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

    def _update_name_completer(self):
        sel = self.selection_panel.get_selection()
        t = sel['type']
        if t not in (2, 3, 4):
            self.action_panel.rename_input.setCompleter(None)
            return

        try:
            year = sel['year']
            if not year: return
            year_dir = BASE_INTERNAL / str(year)
            if not year_dir.exists(): return

            prefix = f"{year - 2003:02d}"
            base = None
            for child in sorted(year_dir.iterdir()):
                if not child.is_dir(): continue
                name = child.name.lower()
                if t == 2: # Characters
                    if (prefix in name and IMAGES_FOLDER in name) or (IMAGES_FOLDER in name):
                        base = child; break
                elif t == 3: # Episodes
                    if '___[' in name: base = child; break
                elif t == 4: # Music
                    if (prefix in name and MUSIC_FOLDER in name) or (MUSIC_FOLDER in name):
                        base = child; break

            if base and base.exists():
                names = [f.stem for f in base.iterdir() if f.is_file()]
                if names:
                    completer = QCompleter(names, self)
                    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                    completer.setFilterMode(Qt.MatchFlag.MatchContains)
                    self.action_panel.rename_input.setCompleter(completer)
                    return
        except Exception: pass
        self.action_panel.rename_input.setCompleter(None)

    def _on_move(self):
        if not self.filepath: return
        sel = self.selection_panel.get_selection()
        decision = {
            'action': 'move',
            'movement_type': sel['type'],
            'year': sel['year'],
            'sub': None,
            'new_name': self.action_panel.get_new_name() or self.filepath.stem
        }
        final_dest = resolve_duplicate(compute_destination(decision, self.filepath))
        self._start_move_task(decision, final_dest)

    def _move_to_subfolder(self, sub_name: str):
        if not self.filepath: return
        self.selection_panel.set_subfolders_enabled(False)
        sel = self.selection_panel.get_selection()
        decision = {
            'action': 'move',
            'movement_type': sel['type'],
            'year': sel['year'],
            'sub': sub_name,
            'new_name': self.action_panel.get_new_name() or self.filepath.stem
        }
        final_dest = resolve_duplicate(compute_destination(decision, self.filepath))
        self._start_move_task(decision, final_dest)

    def _on_apply_custom(self):
        if not self.filepath: return
        folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder", str(self.filepath.parent))
        if not folder: return
        decision = {
            'action': 'move_custom',
            'custom_dir': folder,
            'new_name': self.action_panel.get_new_name() or self.filepath.stem
        }
        newname = sanitize_windows_filename(decision['new_name'])
        final_dest = resolve_duplicate(Path(folder) / (newname + self.filepath.suffix))
        self._start_move_task(decision, final_dest)

    def _start_move_task(self, decision: dict, final_dest: Path):
        self.action_panel.btn_custom.setEnabled(False)
        self.action_panel.btn_move.setEnabled(False)

        src = self.filepath
        if not src: return
        send_character_service_command("pause")

        try:
            src_stat = src.stat()
            src_meta = {
                "atime": src_stat.st_atime,
                "mtime": src_stat.st_mtime,
                "ctime": getattr(src_stat, "st_birthtime", src_stat.st_ctime),
            }
            same_drive = is_same_drive(src, final_dest)
            if same_drive:
                def fast_move():
                    try:
                        final_dest.parent.mkdir(parents=True, exist_ok=True)
                        if move_file_shfileop(src, final_dest):
                            self.state_manager.finalize_background_move(src, final_dest, src_meta)
                    finally:
                        send_character_service_command("resume")
                threading.Thread(target=fast_move, daemon=True).start()
                self.state_manager.handover_active_file()
                self.action_panel.set_progress(0)
                return
        except Exception:
            logging.exception(f"Error in _start_move_task for {src}")
            send_character_service_command("resume")
            self.state_manager.discard_active_file()
            self.action_panel.set_progress(0)
            return

        worker_thread = QtCore.QThread(self)
        worker = FileMoveWorker(src, final_dest)
        worker.moveToThread(worker_thread)
        self._active_workers.add((worker, worker_thread))
        worker_thread.started.connect(worker.run)
        worker.progress.connect(lambda val: self.action_panel.set_progress(val) if self.filepath == src else None)

        def on_finished(ok: bool, copied_path: Path, msg: str):
            send_character_service_command("resume")
            if ok:
                threading.Thread(target=self.state_manager.finalize_background_move,
                                 args=(src, copied_path, src_meta), daemon=True).start()
            worker_thread.quit()

        worker.finished.connect(on_finished)
        worker.finished.connect(worker.deleteLater)
        worker_thread.finished.connect(worker_thread.deleteLater)
        worker_thread.finished.connect(lambda: (self._active_workers.discard((worker, worker_thread)), self._hide_if_idle()))
        worker_thread.start()

        self.state_manager.handover_active_file()
        self.action_panel.set_progress(0)

    def _hide_if_idle(self):
        if self.state_manager.current_state() == State.IDLE and not self.state_manager.has_pending_work():
            self.action_panel.clear()
            self.filepath = None
            self.hide()
