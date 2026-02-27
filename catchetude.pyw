"""
CatchEtude - Main application file.
CatchEtude - Archivo principal de la aplicación.

Organizes downloads by watching the folder and presenting a UI for classification.
Optimized for high-speed classification with background operations and live metadata.
Organiza las descargas vigilando la carpeta y presentando una interfaz para su clasificación.
Optimizado para clasificación de alta velocidad con operaciones en segundo plano y metadatos en vivo.
"""

from __future__ import annotations
import sys
import os
import logging
import traceback
import json
import threading
import time
import win32event
import win32api
import ctypes
import subprocess
from pathlib import Path
from typing import Optional
from datetime import datetime

from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QComboBox, QCompleter, QFileDialog,
    QHBoxLayout, QVBoxLayout, QFileIconProvider, QSystemTrayIcon, QMenu, QListWidget, QCheckBox
)
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import Qt

from config import ( # type: ignore
    APP_NAME, ERROR_ALREADY_EXISTS,
    LOG_PATH, BASE_INTERNAL, CRASH_REPORT_PATH,
    ONEDRIVE_DOCS, ONEDRIVE_DOCTOS_FAMILIA,
    YEARS, ICON_PATH,
    CONFIG_PATH,
    MYAPPID, DOWNLOADS,
    IMAGES_FOLDER, MUSIC_FOLDER, OVERWORLD_FOLDER,
    CHAR_PANEL_ALWAYS, BLUR_LEVEL
)
from utils import (
    resolve_duplicate, flatten_downloads_root,
    configure_dwm_thumbnail_behavior, is_internal_available,
    sanitize_windows_filename, is_temporary, is_file_locked,
    is_same_drive, move_file_shfileop, delete_to_recycle_bin
)
from state_manager import StateManager, State, scan_existing_downloads # type: ignore
from fallback_utils import compute_destination, safe_move_to_conflicts # type: ignore
from character_mgr import CharacterListModel, CharacterDelegate # type: ignore
from watcher_mgr import WatcherThread # type: ignore
from file_worker_mgr import FileMoveWorker # type: ignore
from app_signals_mgr import AppSignals # type: ignore
from subfolder_list_mgr import SubfolderButtonList # type: ignore
from localization import LocalizationManager # type: ignore
from log_mgr import setup_logging, log_signals # type: ignore

class QueueDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate for rendering the download queue with thumbnails/icons."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._thumb_cache = {}

    def paint(self, painter, option, index):
        painter.save()

        path_str = index.data(Qt.ItemDataRole.UserRole)
        is_active = index.data(Qt.ItemDataRole.UserRole + 1)
        p = Path(path_str)

        rect = option.rect

        if is_active:
            # Highlight active file
            painter.fillRect(rect, QtGui.QColor("#e1f5fe"))
            painter.setPen(QtGui.QColor("#01579b"))
        elif option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, option.palette.highlight())
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(option.palette.text().color())

        # Draw icon/thumbnail
        icon_rect = QtCore.QRect(rect.left() + 5, rect.top() + 5, 40, 40)

        if path_str not in self._thumb_cache:
            if p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}:
                reader = QtGui.QImageReader(path_str)
                reader.setAutoTransform(True)
                img_size = reader.size()
                if img_size.isValid():
                    reader.setScaledSize(img_size.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio))
                img = reader.read()
                if not img.isNull():
                    self._thumb_cache[path_str] = QtGui.QPixmap.fromImage(img)
                else:
                    self._thumb_cache[path_str] = QFileIconProvider().icon(QtCore.QFileInfo(path_str))
            else:
                self._thumb_cache[path_str] = QFileIconProvider().icon(QtCore.QFileInfo(path_str))

        obj = self._thumb_cache[path_str]
        if isinstance(obj, QtGui.QPixmap):
            # Center pixmap in icon_rect
            pix_rect = obj.rect()
            pix_rect.moveCenter(icon_rect.center())
            painter.drawPixmap(pix_rect.topLeft(), obj)
        else:
            obj.paint(painter, icon_rect)

        # Draw text
        text_rect = rect.adjusted(55, 0, -5, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, p.name)

        painter.restore()

    def sizeHint(self, option, index):
        return QtCore.QSize(200, 50)

class SubfolderScanner(QtCore.QThread):
    """Background scanner to find the first file in subfolders."""
    result_ready = QtCore.pyqtSignal(str, str)

    def __init__(self, base_path: Path):
        super().__init__()
        self.base_path = base_path
        self._abort = False

    def abort(self):
        self._abort = True

    def run(self):
        try:
            if not self.base_path.exists():
                return

            try:
                with os.scandir(str(self.base_path)) as it:
                    subs = sorted([e.path for e in it if e.is_dir()])
            except Exception:
                return

            for sub_path in subs:
                if self._abort:
                    break

                first_file = "---"
                try:
                    files = []
                    with os.scandir(sub_path) as it_f:
                        for entry in it_f:
                            if entry.is_file():
                                n_low = entry.name.lower()
                                if not (n_low.endswith('.ini') or n_low.endswith('.db')):
                                    files.append(entry.name)
                    if files:
                        files.sort()
                        first_file = files[0]
                except Exception:
                    pass

                self.result_ready.emit(Path(sub_path).name, first_file)
        except Exception:
            logging.exception("Error in SubfolderScanner")

# Set AppUserModelID for Windows Taskbar icon grouping
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(MYAPPID)
except Exception:
    pass

# Ensure single instance
mutex = win32event.CreateMutex(None, False, APP_NAME)
if win32api.GetLastError() == ERROR_ALREADY_EXISTS:
    print("The service is already running")
    sys.exit()

# Configure logging via log_mgr
setup_logging(LOG_PATH)

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

        # Set of active move tasks (to prevent GC)
        self._active_workers = set()

        # Connect signals
        self.signals.file_detected.connect(self.on_file_detected)
        self.signals.queue_empty.connect(self._hide_if_idle)

        self.setWindowTitle(APP_NAME)

        # Window flags: Tool window, stays on top, custom hints
        flags = QtCore.Qt.WindowType.WindowTitleHint | QtCore.Qt.WindowType.CustomizeWindowHint
        flags |= QtCore.Qt.WindowType.Tool
        self.setWindowFlags(flags)
        self.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)

        self.base_width = 820
        self.base_height = 580
        self.setMinimumSize(self.base_width, self.base_height)
        self.resize(self.base_width, self.base_height)

        self._left_panel_visible = False
        self._internal_warned = False
        self.filepath: Optional[Path] = None

        # Check if internal drive E: is available at startup
        # Verificar si la unidad interna E: está disponible al iniciar
        self._internal_available_at_start = is_internal_available()

        self._hide_secure = False
        self._load_config()

        self._setup_server()
        self._sub_scanner = None

        self._build_ui()
        self._build_tray()

        configure_dwm_thumbnail_behavior(self.winId().__int__())

        # Debounce timer for character loading
        self._year_load_timer = QtCore.QTimer(self)
        self._year_load_timer.setSingleShot(True)
        self._year_load_timer.timeout.connect(self._load_characters_for_year)
        self._pending_year = None
        self._char_load_generation = 0

    def _build_ui(self):
        """Builds the main user interface."""
        main_vbox = QVBoxLayout()

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

        # Selection Panel (Left)
        selection_layout = QVBoxLayout()
        top_row = QHBoxLayout()

        # Type Column
        v_type = QVBoxLayout()
        self.lbl_type = QLabel(self.loc.get("lbl_type"))
        self.lbl_type.setText(self.loc.get("lbl_type"))
        v_type.addWidget(self.lbl_type)
        self.list_type = QListWidget()
        self.list_type.addItems([self.loc.get(f"type_{i}") for i in range(1, 9)])
        self.list_type.currentRowChanged.connect(self._on_type_changed)
        v_type.addWidget(self.list_type)
        top_row.addLayout(v_type)

        # Year Column
        v_year = QVBoxLayout()
        self.lbl_year = QLabel(self.loc.get("lbl_years"))
        v_year.addWidget(self.lbl_year)
        self.list_year = QListWidget()
        self.list_year.setFixedWidth(200)
        self.list_year.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
        self.list_year.setFlow(QtWidgets.QListView.Flow.LeftToRight)
        self.list_year.setWrapping(True)
        self.list_year.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self.list_year.setGridSize(QtCore.QSize(60, 28))
        self.list_year.setSpacing(2)
        self.list_year.setStyleSheet("""
            QListWidget::item {
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background-color: #0078d7;
                color: white;
            }
        """)

        for y in YEARS:
            self.list_year.addItem(str(y))

        # Default to 2004
        idx2004 = 0
        for i in range(self.list_year.count()):
            if self.list_year.item(i).text() == '2004':
                idx2004 = i
                break
        self.list_year.setCurrentRow(idx2004)
        self.list_year.currentRowChanged.connect(self._on_year_changed)
        self.list_year.setEnabled(False)
        v_year.addWidget(self.list_year)
        top_row.addLayout(v_year)

        # Subfolder Column
        v_sub = QVBoxLayout()
        self.lbl_sub = QLabel(self.loc.get("lbl_subfolders"))
        v_sub.addWidget(self.lbl_sub)
        self.list_sub = SubfolderButtonList()
        self.list_sub.setEnabled(False)
        self.list_sub.clicked.connect(self._move_to_subfolder)
        v_sub.addWidget(self.list_sub)

        selection_layout.addLayout(top_row)
        selection_layout.addLayout(v_sub)

        self.selection_panel = QWidget()
        self.selection_panel.setLayout(selection_layout)
        root.addWidget(self.selection_panel)

        # Action Panel (Right)
        layout = QVBoxLayout()

        # Preview Section
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(320, 180)
        self.preview_label.setFrameShape(QtWidgets.QFrame.Shape.Box)
        self.preview_label.setScaledContents(False)
        self.preview_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview_label.mousePressEvent = self._toggle_preview
        layout.addWidget(self.preview_label, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)
        self.preview_hidden = False

        self.btn_open = QPushButton(self.loc.get("btn_open"))
        self.btn_open.clicked.connect(self._open_file)
        self.btn_open.setFixedHeight(30)
        self.btn_open.setFixedWidth(100)
        layout.addWidget(self.btn_open, alignment=QtCore.Qt.AlignmentFlag.AlignCenter)

        # Rename Section
        self.lbl_name = QLabel(self.loc.get("lbl_new_name"))
        layout.addWidget(self.lbl_name)
        self.rename_input = QLineEdit()
        self.name_completer = None
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
        self.btn_custom.clicked.connect(self._on_apply_custom)
        footer.addWidget(self.btn_custom)

        self.btn_move = QPushButton(self.loc.get("btn_apply"))
        self.btn_move.setFixedHeight(30)
        self.btn_move.clicked.connect(self._on_move)
        footer.addWidget(self.btn_move)

        self.btn_custom.setEnabled(False)
        self.btn_move.setEnabled(False)
        layout.addLayout(footer)

        # Apply loaded state
        self.hide_secure_cb.setChecked(self._hide_secure)

        self.right_panel = QWidget()
        self.right_panel.setLayout(layout)
        root.addWidget(self.right_panel)

        # Character/Queue Panel
        self.left_panel = QWidget()
        self.left_panel.setFixedWidth(380)
        # Always visible now
        self.left_panel.setVisible(True)
        self._left_panel_visible = True

        lv = QVBoxLayout(self.left_panel)

        # Download Queue (Top of left panel)
        self.lbl_queue = QLabel(self.loc.get("lbl_queue"))
        lv.addWidget(self.lbl_queue)

        self.queue_list_widget = QListWidget()
        self.queue_list_widget.setItemDelegate(QueueDelegate(self))
        self.queue_list_widget.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        # Remove fixed height to let it expand when char_view is hidden
        lv.addWidget(self.queue_list_widget)

        self.signals.queue_updated.connect(self._on_queue_updated)

        # Character Model (Needed for buttons)
        self.char_model = CharacterListModel()
        self.char_model.modelReset.connect(self._update_character_buttons)
        self.char_model.dataChanged.connect(self._update_character_buttons)

        root.addWidget(self.left_panel)

        main_vbox.addLayout(root)
        self.setLayout(main_vbox)
        self.retranslate_ui()


    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview()

    def _update_preview(self):
        """Updates the preview pixmap when window is resized."""
        if self.filepath and not self.preview_hidden:
            self._load_preview(self.filepath)

    def _load_config(self):
        """Loads configuration from config.json."""
        try:
            if CONFIG_PATH.exists():
                with CONFIG_PATH.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    self._hide_secure = data.get("hide_secure", False)
        except Exception:
            logging.exception("Failed to load config")

    def _save_config(self):
        """Saves configuration to config.json."""
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

    def _on_hide_secure_changed(self, state):
        self._hide_secure = (state == Qt.CheckState.Checked.value)
        self._save_config()
        self._update_preview()

    def _setup_server(self):
        """Sets up a QLocalServer to receive commands from other scripts."""
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_server_connection)
        # Using a fixed name for the server
        server_name = "CatchEtudeCommandServer"
        # Cleanup if old server didn't close properly
        QLocalServer.removeServer(server_name)
        if not self._server.listen(server_name):
            logging.error(f"Server could not start: {self._server.errorString()}")
        else:
            logging.info(f"Server listening on {server_name}")

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
                self.hide_secure_cb.setChecked(hide_secure)
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
        """Updates UI text based on the current language."""
        self.btn_delete_header.setText(self.loc.get("btn_header_delete"))
        self.btn_undo.setText(self.loc.get("btn_history"))
        self.btn_lang.setText(self.loc.get("lang_toggle"))
        self.lbl_type.setText(self.loc.get("lbl_type"))
        self.lbl_year.setText(self.loc.get("lbl_years"))
        self.lbl_sub.setText(self.loc.get("lbl_subfolders"))
        self.btn_open.setText(self.loc.get("btn_open"))
        self.lbl_name.setText(self.loc.get("lbl_new_name"))
        self.hide_secure_cb.setText(self.loc.get("btn_secure"))
        self.btn_custom.setText(self.loc.get("btn_apply_custom"))
        self.btn_move.setText(self.loc.get("btn_apply"))
        self.lbl_queue.setText(self.loc.get("lbl_queue"))

        # Update types list
        curr = self.list_type.currentRow()
        self.list_type.blockSignals(True)
        self.list_type.clear()
        self.list_type.addItems([self.loc.get(f"type_{i}") for i in range(1, 9)])
        self.list_type.setCurrentRow(curr)
        self.list_type.blockSignals(False)

    def _on_lang_toggle(self):
        """Toggles the application language."""
        self.loc.toggle_lang()
        self.retranslate_ui()
        self._build_tray() # Refresh tray menu

    def _on_delete_clicked(self):
        """Sends the current file to the recycle bin."""
        if not self.filepath: return

        send_character_service_command("pause")
        try:
            if delete_to_recycle_bin(self.filepath):
                logging.info(f"File sent to recycle bin: {self.filepath}")
                self.state_manager.discard_active_file()
                self.progress.setValue(0)
            else:
                QtWidgets.QMessageBox.warning(self, "Error", "Could not delete file.")
        finally:
            send_character_service_command("resume")

    def _on_undo_clicked(self):
        """Handles the Undo action."""
        send_character_service_command("pause")
        try:
            if self.state_manager.undo_last_move():
                # If successful, StateManager will enqueue the original file,
                # which will trigger on_file_detected and show the window if needed.
                pass
            else:
                QtWidgets.QMessageBox.information(self, "Undo", "Nothing to undo or file no longer exists.")
        finally:
            send_character_service_command("resume")

    def _on_exit_clicked(self):
        """Handles the exit confirmation dialog."""
        reply = QtWidgets.QMessageBox.question(
            self,
            self.loc.get("msg_exit_title"),
            self.loc.get("msg_exit_confirm"),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No
        )
        if reply == QtWidgets.QMessageBox.StandardButton.Yes:
            QApplication.quit()

    def _build_tray(self):
        """Builds the system tray icon and menu."""
        icon = QIcon.fromTheme("folder-downloads")
        if icon.isNull():
            icon = QIcon(ICON_PATH)

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
        self.tray_menu.addAction(quit_action)

        self.tray.setContextMenu(self.tray_menu)
        self.tray.show()

    def _show_logs(self):
        """Signals the watchdog service to show the log viewer."""
        socket = QLocalSocket()
        socket.connectToServer("CatchEtudeLogServer")
        if socket.waitForConnected(100):
            data = json.dumps({"cmd": "show"})
            socket.write(data.encode('utf-8'))
            socket.waitForBytesWritten(100)
            socket.disconnectFromServer()

    def _bring_and_center(self):
        """Shows the window and centers it on the current screen."""
        self.show()
        screen = self.screen().availableGeometry()
        size = self.geometry()
        x = (screen.width() - size.width()) // 2
        y = (screen.height() - size.height()) // 2
        self.move(x, y)
        self.raise_()
        self.activateWindow()

    def _restart_service(self):
        """Restarts the application using the auxiliary script."""
        pid = os.getpid()
        script_path = str(Path(__file__).resolve())
        restart_script = str(Path(__file__).resolve().parent / "restart_app.py")

        # Start the restart script decoupled from the current process group
        # Using CREATE_NEW_PROCESS_GROUP (0x10) which is safer for Windows.
        # DETACHED_PROCESS (0x08) often causes WinError 87 in GUI apps.
        flags = 0x00000010 # CREATE_NEW_PROCESS_GROUP
        try:
            subprocess.Popen([sys.executable, restart_script, str(pid), script_path], creationflags=flags)
        except Exception:
            logging.exception("Failed to start restart script with flags, trying without.")
            subprocess.Popen([sys.executable, restart_script, str(pid), script_path])

        # Exit the current process
        QApplication.quit()

    def _rescan_downloads(self):
        """Manually triggers a scan of the Downloads folder."""
        threading.Thread(
            target=lambda: scan_existing_downloads(self.state_manager),
            daemon=True
        ).start()

    def _on_order_pending_clicked(self):
        """Opens a dialog to choose a folder and enqueues its contents."""
        folder = QFileDialog.getExistingDirectory(self, "Select Folder to Process", str(DOWNLOADS))
        if folder:
            self._process_pending_folder(Path(folder))

    def _run_pendings(self):
        """Runs the pendings_exec.pyw script without console."""
        try:
            pendings_script = str(Path(__file__).resolve().parent / "pendings_exec.pyw")
            # Use pythonw.exe to run without console
            python_exe = sys.executable
            if python_exe.lower().endswith("python.exe"):
                python_exe = python_exe[:-10] + "pythonw.exe"

            subprocess.Popen([python_exe, pendings_script], creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            logging.info(f"Started pendings_exec.pyw with {python_exe}")
        except Exception:
            logging.exception("Failed to run pendings script")

    def _process_pending_folder(self, folder: Path):
        """Recursively enqueues files from a folder."""
        def worker():
            files = sorted(folder.rglob('*'))
            for f in files:
                if f.is_file() and not is_temporary(f):
                    self.state_manager.enqueue_file(f)
        threading.Thread(target=worker, daemon=True).start()

    def _warn_internal_missing(self):
        if self._internal_warned:
            return
        self._internal_warned = True
        QtWidgets.QMessageBox.warning(
            self,
            "Almacenamiento no disponible",
            "El disco interno (E:\\_Internal) no está conectado.\n"
            "Las opciones dependientes quedarán deshabilitadas."
        )

    @QtCore.pyqtSlot(str)
    def on_file_detected(self, path_str: str):
        """
        Triggered when a new file is ready for processing.
        Se activa cuando un nuevo archivo está listo para ser procesado.
        """
        p = Path(path_str)
        if not p.exists():
            logging.info(f"File {p} no longer available")
            return

        if self.state_manager.current_state() != State.FILE_DETECTED:
            return

        if not self.state_manager.declare_user_deciding():
            return

        # Load file info
        self.filepath = p
        self.rename_input.setText(p.stem)
        self._load_preview(p)
        self.progress.setValue(0)

        # Enable buttons
        self.btn_custom.setEnabled(True)

        # Refresh UI state based on current selection
        self._on_type_changed(self.list_type.currentRow())

        # Update subfolders if needed (keep current type/year)
        self._refresh_classification_ui()

        # Show window (only if internal drive was available at start)
        # Mostrar ventana (solo si la unidad interna estaba disponible al inicio)
        if not self.isVisible() and self._internal_available_at_start:
            self.resize(self.base_width + self.left_panel.width(), self.height())
            self.show()
            self.raise_()
            self.activateWindow()

        # Update character panel visibility
        is_char_type = (self.list_type.currentRow() + 1 == 2)
        self._update_panel_layout(is_char_type)
        self._update_name_completer()

    def _refresh_classification_ui(self):
        """Refreshes the subfolder list based on current type and year."""
        t = self.list_type.currentRow() + 1
        if t in (2, 3, 4, 8):
            try:
                item = self.list_year.currentItem()
                if item:
                    year = int(item.text())
                    self._populate_subs_for_year(year)
            except ValueError:
                pass
        elif t in (5, 6):
            base = ONEDRIVE_DOCS if t == 5 else ONEDRIVE_DOCTOS_FAMILIA
            self._populate_subfolders(base)
        else:
            self.list_sub.clear()
            self.list_sub.setEnabled(False)

    def _update_panel_layout(self, show_left: bool):
        """Updates the window size and panel visibility."""
        # Always show left panel now as it contains the queue
        if not self._left_panel_visible:
            self.left_panel.setVisible(True)
            self.resize(self.base_width + self.left_panel.width(), self.height())
            self._left_panel_visible = True

    def _load_preview(self, p: Path):
        """Loads a preview of the file (image or icon)."""
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
        """Applies a 90% blur effect with a partial reveal at the bottom."""
        if image.isNull():
            return image

        # Create a blurred version of the entire image
        # Using a simple scaling trick for fast blur if QGraphicsBlurEffect is too heavy for direct QImage

        # Method: Scale down and up for a blur effect
        # We'll use a small size for the blurred part
        blur_radius = BLUR_LEVEL
        small = image.scaled(image.width() // blur_radius, image.height() // blur_radius,
                             Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        blurred = small.scaled(image.width(), image.height(),
                               Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)

        # Now create the final image combining blurred (90% top) and original (bottom)
        result = QtGui.QImage(image.size(), QtGui.QImage.Format.Format_ARGB32)
        result.fill(Qt.GlobalColor.transparent)

        painter = QtGui.QPainter(result)

        # Define the reveal area (bottom 15% for example)
        reveal_height = int(image.height() * 0.15)
        blur_height = image.height() - reveal_height

        # Draw blurred part
        painter.drawImage(QtCore.QRect(0, 0, image.width(), blur_height),
                          blurred,
                          QtCore.QRect(0, 0, image.width(), blur_height))

        # Draw original part at the bottom
        painter.drawImage(QtCore.QRect(0, blur_height, image.width(), reveal_height),
                          image,
                          QtCore.QRect(0, blur_height, image.width(), reveal_height))

        painter.end()
        return result

    def _toggle_preview(self, event):
        if not self.filepath: return
        self.preview_hidden = not self.preview_hidden
        if self.preview_hidden:
            self.preview_label.clear()
            self.preview_label.setPixmap(QFileIconProvider().icon(QtCore.QFileInfo(str(self.filepath))).pixmap(32, 32))
        else:
            self._load_preview(self.filepath)

    def _open_file(self):
        if self.filepath:
            os.startfile(str(self.filepath))

    def _on_type_changed(self, idx):
        t = idx + 1
        if t in (2, 3, 4, 7, 8) and not is_internal_available():
            self._warn_internal_missing()
            self.list_sub.clear()
            self.list_sub.setEnabled(False)
            self.list_year.setEnabled(False)
            return

        self._update_panel_layout(t == 2)

        # Disable Apply button for fast-move types
        self.btn_move.setEnabled(t not in (2, 3, 4, 6, 8))

        if t == 1:
            self.list_year.setEnabled(False)
            self.list_sub.clear()
            self.list_sub.setEnabled(False)
        elif t in (2, 3, 4, 8):
            self.list_year.setEnabled(True)
            self._on_year_changed(self.list_year.currentRow())
        elif t in (5, 6):
            self.list_year.setEnabled(False)
            self._populate_subfolders(ONEDRIVE_DOCS if t == 5 else ONEDRIVE_DOCTOS_FAMILIA)
        elif t == 7:
            self.list_year.setEnabled(False)
            self.list_sub.clear()
            self.list_sub.setEnabled(False)

        self._update_name_completer()

    def _on_year_changed(self, idx):
        if not is_internal_available() or idx < 0:
            self.list_sub.clear()
            self.list_sub.setEnabled(False)
            return

        try:
            item = self.list_year.currentItem()
            if not item: return
            year = int(item.text())
        except ValueError:
            return

        t = self.list_type.currentRow() + 1
        if t in (2, 3, 4, 8):
            self._populate_subs_for_year(year)

        if t == 2:
            self._pending_year = year
            self._year_load_timer.start(400) # Debounce load

    def _populate_subs_for_year(self, year: int):
        """
        Finds the appropriate base folder for the given year and type,
        then populates the subfolders list.
        """
        year_dir = BASE_INTERNAL / str(year)
        if not (year_dir.exists() and year_dir.is_dir()):
            logging.warning(f"Year directory not found or not a directory: {year_dir}")
            self.list_sub.clear()
            self.list_sub.setEnabled(False)
            return

        prefix = f"{year - 2003:02d}"
        t = self.list_type.currentRow() + 1
        base = None

        try:
            # Multi-pattern search for better robustness
            for child in sorted(year_dir.iterdir()):
                if not child.is_dir():
                    continue

                name = child.name.lower()
                if t == 2: # Characters
                    if (prefix in name and IMAGES_FOLDER in name) or (IMAGES_FOLDER in name):
                        base = child
                        break
                elif t == 3: # Episodes
                    if '___[' in name:
                        base = child
                        break
                elif t == 4: # Music
                    if (prefix in name and MUSIC_FOLDER in name) or (MUSIC_FOLDER in name):
                        base = child
                        break
                elif t == 8: # Overworld
                    if (prefix in name and OVERWORLD_FOLDER in name) or (OVERWORLD_FOLDER in name):
                        base = child
                        break
        except Exception:
            logging.exception(f"Error accessing year directory: {year_dir}")

        # Fallback if no matching folder was found
        if base is None:
            logging.info(f"No matching folder found for type {t} in {year_dir}, using fallback.")
            if t == 2:
                base = year_dir / f"{prefix}. {IMAGES_FOLDER}"
            elif t == 4:
                base = year_dir / f"{prefix}. {MUSIC_FOLDER}"
            elif t == 8:
                base = year_dir / f"{prefix}. {OVERWORLD_FOLDER}"
            else:
                base = year_dir

        if not base.exists():
            QtWidgets.QMessageBox.warning(
                self,
                "Carpeta no encontrada / Folder not found",
                f"No se encontró la carpeta base para la selección actual:\n{base}\n\n"
                "Por favor, verifique que la unidad E: esté conectada correctamente."
            )

        self._populate_subfolders(base)

    def _populate_subfolders(self, base: Path):
        """Populates list_sub with subdirectories from the base path."""
        self.list_sub.clear()

        if self._sub_scanner:
            self._sub_scanner.abort()
            self._sub_scanner.wait()
            self._sub_scanner = None

        try:
            if base.exists() and base.is_dir():
                subs = [c.name for c in sorted(base.iterdir()) if c.is_dir()]
                if subs:
                    self.list_sub.add_subfolders(subs)
                    self.list_sub.setEnabled(True)
                    logging.info(f"Populated {len(subs)} subfolders from {base.name}")

                    t = self.list_type.currentRow() + 1
                    if t == 3:
                        self._sub_scanner = SubfolderScanner(base)
                        self._sub_scanner.result_ready.connect(
                            lambda name, ffile: self.list_sub.update_button(name, ffile)
                        )
                        self._sub_scanner.start()
                    elif t == 2:
                        self._update_character_buttons()
                    return
                else:
                    logging.info(f"No subfolders found in {base}")
            else:
                logging.warning(f"Base path for subfolders does not exist: {base}")
        except Exception:
            logging.exception(f"Failed to populate subfolders from {base}")

        self.list_sub.setEnabled(False)
        self._update_name_completer()

    def _load_characters_for_year(self):
        if self._pending_year is None: return
        self._char_load_generation += 1
        # Clear the model immediately to show the user that a new year is loading
        self.char_model.clear_data()
        self.char_model.request_characters(self._pending_year, self._char_load_generation)

    @QtCore.pyqtSlot(list, str)
    def _on_queue_updated(self, queue_list: list[Path], active_path_str: str):
        """Updates the download queue UI list."""
        self.queue_list_widget.clear()
        for p in queue_list:
            item = QtWidgets.QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            item.setData(Qt.ItemDataRole.UserRole + 1, str(p) == active_path_str)
            self.queue_list_widget.addItem(item)

    def _update_character_buttons(self):
        """Updates subfolder buttons with character metadata."""
        t = self.list_type.currentRow() + 1
        if t != 2:
            return

        for c in self.char_model.items:
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

            self.list_sub.update_button(folder_name, line2, line3)

    def _update_name_completer(self):
        """Updates the name completer based on the current selection."""
        t = self.list_type.currentRow() + 1
        if t not in (2, 3, 4):
            self.rename_input.setCompleter(None)
            self.name_completer = None
            return

        try:
            item_year = self.list_year.currentItem()
            if not item_year: return
            year = int(item_year.text())
            year_dir = BASE_INTERNAL / str(year)
            if not (year_dir.exists() and year_dir.is_dir()):
                return

            prefix = f"{year - 2003:02d}"
            base = None

            # Use matching logic consistent with _populate_subs_for_year
            for child in sorted(year_dir.iterdir()):
                if not child.is_dir():
                    continue

                name = child.name.lower()
                if t == 2: # Characters
                    if (prefix in name and IMAGES_FOLDER in name) or (IMAGES_FOLDER in name):
                        base = child
                        break
                elif t == 3: # Episodes
                    if '___[' in name:
                        base = child
                        break
                elif t == 4: # Music
                    if (prefix in name and MUSIC_FOLDER in name) or (MUSIC_FOLDER in name):
                        base = child
                        break

            # With buttons, there is no single "selected" subfolder for the completer
            # so we'll just use the base folder for now.

            if base and base.exists():
                names = [f.stem for f in base.iterdir() if f.is_file()]
                if names:
                    self.name_completer = QCompleter(names, self)
                    self.name_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                    self.name_completer.setFilterMode(Qt.MatchFlag.MatchContains)
                    self.rename_input.setCompleter(self.name_completer)
                    return
        except Exception:
            pass

        self.rename_input.setCompleter(None)

    def _on_move(self):
        """Handles the standard 'Apply' action."""
        if not self.filepath: return

        item_year = self.list_year.currentItem()

        decision = {
            'action': 'move',
            'movement_type': self.list_type.currentRow() + 1,
            'year': int(item_year.text()) if self.list_year.isEnabled() and item_year else None,
            'sub': None,
            'new_name': self.rename_input.text().strip() or self.filepath.stem
        }
        final_dest = resolve_duplicate(compute_destination(decision, self.filepath))
        self._start_move_task(decision, final_dest)

    def _move_to_subfolder(self, sub_name: str):
        """
        Moves the file to the specified subfolder immediately.
        Mueve el archivo a la subcarpeta especificada inmediatamente.
        """
        if not self.filepath: return

        # Disable subfolder list while moving
        self.list_sub.setEnabled(False)

        item_year = self.list_year.currentItem()

        decision = {
            'action': 'move',
            'movement_type': self.list_type.currentRow() + 1,
            'year': int(item_year.text()) if self.list_year.isEnabled() and item_year else None,
            'sub': sub_name,
            'new_name': self.rename_input.text().strip() or self.filepath.stem
        }
        final_dest = resolve_duplicate(compute_destination(decision, self.filepath))
        self._start_move_task(decision, final_dest)

    def _on_apply_custom(self):
        """Handles the 'Apply Custom' action with background worker."""
        if not self.filepath: return
        folder = QFileDialog.getExistingDirectory(self, "Select Destination Folder", str(self.filepath.parent))
        if not folder: return

        decision = {
            'action': 'move_custom',
            'custom_dir': folder,
            'new_name': self.rename_input.text().strip() or self.filepath.stem
        }
        newname = sanitize_windows_filename(decision['new_name'])
        final_dest = resolve_duplicate(Path(folder) / (newname + self.filepath.suffix))
        self._start_move_task(decision, final_dest)

    def _start_move_task(self, decision: dict, final_dest: Path):
        """Starts the background move worker and handles completion."""
        # Disable buttons while we transition
        self.btn_custom.setEnabled(False)
        self.btn_move.setEnabled(False)

        src = self.filepath
        if not src: return

        # Pause character service scanning to avoid I/O contention
        send_character_service_command("pause")

        try:
            # Capture metadata immediately to avoid race conditions if file is moved
            src_stat = src.stat()
            src_meta = {
                "atime": src_stat.st_atime,
                "mtime": src_stat.st_mtime,
                "ctime": getattr(src_stat, "st_birthtime", src_stat.st_ctime),
            }

            # Check if same drive to use SHFileOperation
            same_drive = is_same_drive(src, final_dest)
            logging.info(f"Preparing move for {src.name} -> {final_dest}. Same drive: {same_drive}")

            if same_drive:
                logging.info(f"Same drive detected for {src.name}. Using SHFileOperation.")

                def fast_move():
                    try:
                        # Ensure destination directory exists
                        final_dest.parent.mkdir(parents=True, exist_ok=True)

                        if move_file_shfileop(src, final_dest):
                            self.state_manager.finalize_background_move(src, final_dest, src_meta)
                        else:
                            logging.error(f"SHFileOperation failed for {src}")
                    except Exception:
                        logging.exception(f"Exception in background fast_move for {src}")
                    finally:
                        send_character_service_command("resume")

                threading.Thread(target=fast_move, daemon=True).start()

                self.state_manager.handover_active_file()
                self.progress.setValue(0)
                return

        except FileNotFoundError:
            logging.warning(f"File not found when starting move task: {src}. It may have been moved already.")
            send_character_service_command("resume")
            # Discard and move on
            self.state_manager.discard_active_file()
            self.progress.setValue(0)
            return
        except Exception:
            logging.exception(f"Unexpected error in _start_move_task preparation for {src}")
            send_character_service_command("resume")
            self.state_manager.discard_active_file()
            self.progress.setValue(0)
            return

        # Create worker and thread
        worker_thread = QtCore.QThread(self)
        worker = FileMoveWorker(src, final_dest)
        worker.moveToThread(worker_thread)

        # Keep references
        self._active_workers.add((worker, worker_thread))

        worker_thread.started.connect(worker.run)
        # Use a local reference for progress if it's still the active file
        def update_progress(val):
            if self.filepath == src:
                self.progress.setValue(val)
        worker.progress.connect(update_progress)

        def on_finished(ok: bool, copied_path: Path, msg: str):
            send_character_service_command("resume")
            if ok:
                # Finalize in background thread
                threading.Thread(target=self.state_manager.finalize_background_move,
                                 args=(src, copied_path, src_meta), daemon=True).start()
            else:
                logging.error(f"Copy failed for {src}: {msg}")
                # We can't easily show a message box if the user is already on the next file,
                # but we'll log it and fallback to conflicts in StateManager if possible.

            worker_thread.quit()

        worker.finished.connect(on_finished)
        worker.finished.connect(worker.deleteLater)
        worker_thread.finished.connect(worker_thread.deleteLater)

        def cleanup_refs():
            self._active_workers.discard((worker, worker_thread))
            # If no more files and no active workers, we can check for idle hide
            if not self._active_workers:
                self._hide_if_idle()

        worker_thread.finished.connect(cleanup_refs)
        worker_thread.start()

        # HOT-SWAP: Tell StateManager we are ready for the next file IMMEDIATELY
        self.state_manager.handover_active_file()

        # Reset UI fields for next file (will be overwritten if another is detected)
        self.progress.setValue(0)

    def _hide_if_idle(self):
        if self.state_manager.current_state() == State.IDLE and not self.state_manager.has_pending_work():
            self.rename_input.setText("")
            self.filepath: Optional[Path] = None
            self.preview_label.clear()
            self.hide()

def add_to_startup(name: str, path_to_exe: str, production: bool):
    """Adds the application to Windows startup."""
    if production:
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, f"\"{path_to_exe}\"")
            winreg.CloseKey(key)
            logging.info("Added to Windows startup")
        except Exception:
            logging.exception("Failed to add to startup")

def crash_handler(etype, value, tb):
    """Global exception hook to record crashes."""
    err_msg = "".join(traceback.format_exception(etype, value, tb))
    logging.critical(f"Unhandled exception:\n{err_msg}")
    try:
        CRASH_REPORT_PATH.write_text(err_msg, encoding='utf-8')
    except Exception:
        pass

def start_watchdog():
    """Starts the parallel watchdog service using os.startfile."""
    try:
        watchdog_script = str(Path(__file__).resolve().parent / "catch_watchdog.pyw")
        # Use startfile to leverage shell association for .py files
        os.startfile(watchdog_script)
        logging.info("Watchdog started via startfile")
    except Exception:
        logging.exception("Failed to start watchdog via startfile")

def send_character_service_command(cmd: str, **kwargs):
    """Sends a command to the parallel character service."""
    socket = QLocalSocket()
    socket.connectToServer("CatchEtudeCharacterServer")
    if socket.waitForConnected(200):
        data = {"cmd": cmd}
        data.update(kwargs)
        socket.write(json.dumps(data).encode('utf-8'))
        socket.waitForBytesWritten(200)
        socket.disconnectFromServer()

def start_character_service():
    """Starts the parallel character data service using os.startfile."""
    try:
        service_script = str(Path(__file__).resolve().parent / "character_service.pyw")
        os.startfile(service_script)
        logging.info("Character service started via startfile")
    except Exception:
        logging.exception("Failed to start character service via startfile")

def main():
    sys.excepthook = crash_handler

    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(ICON_PATH))
    app.setQuitOnLastWindowClosed(False)

    try:
        # Clear previous crash report
        if CRASH_REPORT_PATH.exists():
            CRASH_REPORT_PATH.unlink()

        if not CONFIG_PATH.exists():
            with CONFIG_PATH.open('w', encoding='utf-8') as f: json.dump({}, f)

        start_watchdog()
        start_character_service()

        state_manager = StateManager()
        signals = AppSignals()
        state_manager.notifier = signals

        watcher = WatcherThread(state_manager.enqueue_file)
        app.aboutToQuit.connect(watcher.stop)
        watcher.start()

        threading.Thread(target=lambda: (flatten_downloads_root(), scan_existing_downloads(state_manager)), daemon=True).start()

        win = MainWindow(state_manager, signals) #noqa

        maintenance_timer = QtCore.QTimer()
        maintenance_timer.setInterval(3000)
        maintenance_timer.timeout.connect(state_manager.maintenance_tick)
        maintenance_timer.start()

        # Periodic rescan every 30 minutes / Reescaneo periódico cada 30 minutos
        rescan_timer = QtCore.QTimer()
        rescan_timer.setInterval(30 * 60 * 1000)
        rescan_timer.timeout.connect(lambda: threading.Thread(
            target=scan_existing_downloads, args=(state_manager,), daemon=True).start())
        rescan_timer.start()

        # Startup
        mypath = str(Path(__file__).resolve())
        try:
            add_to_startup(APP_NAME, mypath, True)
        except Exception:
            logging.exception("add_to_startup failed")

        sys.exit(app.exec())
    except Exception:
        logging.exception("Unhandled exception in main")

if __name__ == "__main__":
    main()
