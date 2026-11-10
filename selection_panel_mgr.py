"""
Selection panel component for CatchEtude.
Componente del panel de selección para CatchEtude.
"""

import os
import shutil
import logging
import subprocess
import sys
from pathlib import Path
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QHBoxLayout
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QListWidgetItem

import config
from localization import LocalizationManager
from subfolder_list_mgr import SubfolderButtonList
from classification_mgr import (
    get_base_path_for_type_year,
    get_base_path_for_docs,
    EpisodeSubfolderListWorker,
    SubfolderScanner,
)
from utils import is_internal_available, delete_to_recycle_bin
from years_selector import YearsTableWidget
from episode_cache_mgr import EpisodeCacheManager
from overworld_ipc_mgr import OverworldServiceClient
from subfolder_queue_addmore import populate_add_to_queue_menu
from ui_utils_mgr import load_stylesheet

class SelectionPanel(QWidget):
    """
    Panel for selecting classification type, year, and subfolder.
    Panel para seleccionar el tipo de clasificación, año y subcarpeta.
    """
    subfolder_clicked = QtCore.pyqtSignal(str)
    copy_to_subfolder_clicked = QtCore.pyqtSignal(str)
    subfolders_refreshed = QtCore.pyqtSignal()
    folder_structure_changed = QtCore.pyqtSignal()
    move_all_in_folder_clicked = QtCore.pyqtSignal(str)
    move_and_open_file_clicked = QtCore.pyqtSignal(str)
    move_and_open_folder_clicked = QtCore.pyqtSignal(str)
    move_all_and_open_folder_clicked = QtCore.pyqtSignal(str)
    hide_temporal_clicked = QtCore.pyqtSignal()
    move_and_enable_secure_clicked = QtCore.pyqtSignal(str)
    type_changed = QtCore.pyqtSignal(int)
    year_changed = QtCore.pyqtSignal(int)
    keep_action_clicked = QtCore.pyqtSignal(str)
    linear_docs_action_clicked = QtCore.pyqtSignal(str)
    undo_clicked = QtCore.pyqtSignal()
    status_requested = QtCore.pyqtSignal(str)

    def __init__(self, parent=None, plugin_mgr=None):
        super().__init__(parent)
        self.plugin_mgr = plugin_mgr
        self.loc = LocalizationManager()
        self._app_icon = QIcon(config.ICON_PATH)
        
        self._type_icon_paths = {
            1: f"{config.APP_DIR}/assets/descargas.png",
            2: f"{config.APP_DIR}/assets/me-gusta.png",
            3: f"{config.APP_DIR}/assets/película.png",
            4: f"{config.APP_DIR}/assets/música.png",
            5: f"{config.APP_DIR}/assets/aula-de-google.png",
            6: f"{config.APP_DIR}/assets/identificación-verificada.png",
            7: f"{config.APP_DIR}/assets/adobe-acrobat.png",
            8: f"{config.APP_DIR}/assets/mundo.png",
        }
        
        self._sub_scanner = None
        self._sub_scanner_workers = set()
        self._episode_list_workers = set()
        self._sub_scan_generation = 0
        self._overworld_client = OverworldServiceClient(self)
        self._overworld_client.result_ready.connect(self._on_overworld_result)
        self._overworld_client.finished_ready.connect(
            lambda gen: setattr(self, "_overworld_refresh_pending", False)
        )
        self._overworld_generation = 0
        self._last_loaded_type = None
        self._last_loaded_year = None
        self._recent_subfolders = []
        self._recent_items_by_label = {}
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
                
        # -------------------
        # Type Column
        # -------------------
        type_decition_bar = QHBoxLayout()
        type_decition_bar.setContentsMargins(0, 0, 0, 0)
        type_decition_bar.setSpacing(8)

        self.list_type = QListWidget()
        self.list_type.setMaximumHeight(50)
        self.list_type.setViewMode(QListWidget.ViewMode.IconMode)
        self.list_type.setFlow(QListWidget.Flow.TopToBottom)
        self.list_type.setMovement(QListWidget.Movement.Static)
        self.list_type.setTextElideMode(QtCore.Qt.TextElideMode.ElideNone)
        self.list_type.setIconSize(QSize(32, 32))
        self.list_type.setGridSize(QSize(42, 42))
        self.list_type.setSpacing(10)
        self.list_type.setFixedHeight(45)
        self._fill_type_list()
        self.list_type.currentRowChanged.connect(self._on_type_changed)
        self.list_type.setStyleSheet(load_stylesheet("selection_panel_type.css"))
        
        type_decition_bar.addWidget(self.list_type, 1)
        layout.addLayout(type_decition_bar)
        

        # ==========================
        # Fila de Desicion y Años (top row)
        # ==========================
        bottom_h_row = QHBoxLayout()

        # -------------------
        # Year Column (top row)
        # -------------------
        
        v_year = QVBoxLayout()

        self.list_year = YearsTableWidget(config.YEARS, self)
        self.list_year.setMaximumHeight(430)
        self.list_year.setMaximumWidth(100)
        self.list_year.setStyleSheet(load_stylesheet("selection_panel_year.css"))
        self.list_year.yearChanged.connect(self._on_year_changed)
        self.list_year.setEnabled(False)

        v_year.addWidget(self.list_year)
        bottom_h_row.addLayout(v_year)
        
        
        # ==========================
        # Fila de las subcarpetas
        # ==========================

        # Subfolder Column
        v_sub = QVBoxLayout()
        self.list_sub = SubfolderButtonList()
        self.list_sub.setEnabled(False)
        self.list_sub.clicked.connect(self._on_subfolder_clicked)
        self.list_sub.rightClicked.connect(self._on_subfolder_right_clicked)
        self.list_sub.emptyCreateClicked.connect(self._on_empty_create_folder_clicked)
        v_sub.addWidget(self.list_sub)
        
        bottom_h_row.addLayout(v_sub)
        layout.addLayout(bottom_h_row)
        

    def retranslate_ui(self):
        curr = self.list_type.currentRow()
        self._fill_type_list(curr)
        if self._selected_type_id() == 0:
            self._populate_recent_subfolders()
        else:
            self.refresh_classification_ui(force=True)


    def _selected_type_id(self) -> int:
        """Return the classification ID stored on the selected decision item."""
        item = self.list_type.currentItem()
        if item is None:
            return 0
        try:
            return int(item.data(QtCore.Qt.ItemDataRole.UserRole) or 0)
        except (TypeError, ValueError):
            return 0

    def _on_subfolder_clicked(self, name: str):
        t = self._selected_type_id()
        if t == 0:
            recent = self._recent_items_by_label.get(name)
            if recent is not None:
                self._choose_recent_subfolder(recent)
            return
        if t == 1:
            self.keep_action_clicked.emit(name)
            return
        if t == 7:
            self.linear_docs_action_clicked.emit(name)
            return

        self._remember_recent_subfolder(name)
        self.subfolder_clicked.emit(name)

    def _remember_recent_subfolder(self, name: str):
        t = self._selected_type_id()
        if t not in (2, 3, 4, 5, 6, 8) or not name:
            return

        year = self.list_year.current_year() if t in (2, 3, 4, 8) else None
        if t in (2, 3, 4, 8) and year is None:
            return

        recent = {"type": t, "year": year, "name": name}
        self._recent_subfolders = [
            item for item in self._recent_subfolders
            if not (
                item.get("type") == t
                and item.get("year") == year
                and item.get("name") == name
            )
        ]
        self._recent_subfolders.insert(0, recent)
        del self._recent_subfolders[20:]

    def _recent_subfolder_label(self, recent: dict) -> str:
        """Build a unique, readable list label while retaining the real folder name."""
        type_id = recent.get("type")
        type_label = self.loc.get(f"type_{type_id}")
        year = recent.get("year")
        classification = f"{type_label} ({year})" if year is not None else type_label
        return f'{recent["name"]} — {classification}'

    def _populate_recent_subfolders(self):
        """Display the MRU folders directly in the subfolder list."""
        self._cancel_subfolder_scans()
        self._last_loaded_type = None
        self._last_loaded_year = None
        self.list_year.setEnabled(False)
        self._recent_items_by_label = {}

        if not self._recent_subfolders:
            self.list_sub.show_message_placeholder(
                self.loc.get("menu_no_recently_folders")
            )
            self.list_sub.setEnabled(True)
            self.subfolders_refreshed.emit()
            return

        labels = []
        for recent in self._recent_subfolders[:20]:
            label = self._recent_subfolder_label(recent)
            # The classification/year suffix disambiguates folders with equal names.
            self._recent_items_by_label[label] = recent
            labels.append(label)

        self.list_sub.add_subfolders(labels)
        self.list_sub.setEnabled(True)
        self.subfolders_refreshed.emit()

    def _choose_recent_subfolder(self, recent: dict):
        type_id = recent.get("type")
        year = recent.get("year")
        name = recent.get("name")
        if type_id not in (2, 3, 4, 5, 6, 8) or not name:
            return
        if type_id in (2, 3, 4, 8) and year is None:
            return

        # Decision rows retain their original classification IDs: row 0 is Recent.
        row = type_id
        if 0 < row < self.list_type.count():
            self.list_type.setCurrentRow(row)

        if year is not None:
            if year in getattr(config, "NONCANON_YEARS", ()):
                self.list_year._select_hidden_year(year)
            else:
                self.list_year._select_year(year)

        self.subfolder_clicked.emit(name)

    def _on_type_changed(self, idx):
        if idx < 0:
            return
        if idx == 0:
            self._populate_recent_subfolders()
            return

        self._last_non_recent_row = idx
        type_id = self._selected_type_id()
        if not type_id:
            return

        # Never block the UI waiting for a stale episode scan to finish.
        self._cancel_subfolder_scans()
        self.type_changed.emit(type_id)
        self.refresh_classification_ui()

    def _on_year_changed(self, year):
        if year >= 0:
            self.year_changed.emit(year)
            self.refresh_classification_ui()

    def get_selection(self):
        type_id = self._selected_type_id()
        if type_id == 0:
            # Recent is a navigation view, not a movement destination.
            previous_item = self.list_type.item(self._last_non_recent_row)
            if previous_item is not None:
                type_id = int(
                    previous_item.data(QtCore.Qt.ItemDataRole.UserRole) or 1
                )
            else:
                type_id = 1

        return {
            'type': type_id,
            'year': self.list_year.current_year()
        }

    def refresh_classification_ui(self, force=False):
        t = self._selected_type_id()
        if t == 0:
            return
        year = self.list_year.current_year() if t in (2, 3, 4, 7, 8) else None

        if not force and t == self._last_loaded_type and year == self._last_loaded_year:
            if t in (2, 3, 4, 8):
                if year:
                    self.list_year.setEnabled(True)
                    self.list_sub.setEnabled(True)
                else:
                    self.list_sub.setEnabled(False)
            elif t == 1:
                self.list_sub.setEnabled(True)
                self.list_year.setEnabled(False)
            elif t == 7:
                self.list_sub.setEnabled(True)
                self.list_year.setEnabled(True)
            elif t in (5, 6):
                self.list_sub.setEnabled(True)
                self.list_year.setEnabled(False)
            else:
                self.list_sub.setEnabled(False)
                self.list_year.setEnabled(False)
            return

        self._last_loaded_type = t
        self._last_loaded_year = year

        if t == 1:
            self.list_sub.add_subfolders([
                self.loc.get("keep_this_file"),
                self.loc.get("keep_this_file_open_file"),
                self.loc.get("keep_this_file_open_folder"),
                self.loc.get("keep_all_files"),
                self.loc.get("keep_all_files_open_folder"),
                self.loc.get("save_another_folder"),
                self.loc.get("save_another_folder_open_file"),
                self.loc.get("save_another_folder_open_folder"),
                self.loc.get("save_all_another_folder"),
                self.loc.get("save_all_another_folder_open_folder"),
            ])
            self.list_sub.setEnabled(True)
            self.list_year.setEnabled(False)
        elif t == 7:
            self.list_sub.add_subfolders([
                "Guardar en el año seleccionado",
                "Guardar en el año actual"
            ])
            self.list_sub.setEnabled(True)
            self.list_year.setEnabled(True)
        elif t in (2, 3, 4, 8):
            if year:
                base = get_base_path_for_type_year(t, year)
                self._populate_subfolders(base)
                self.list_year.setEnabled(True)
            else:
                self.list_sub.clear()
                self.list_sub.setEnabled(False)
        elif t in (5, 6):
            base = get_base_path_for_docs(t)
            self._populate_subfolders(base)
            self.list_year.setEnabled(False)
        else:
            self.list_sub.clear()
            self.list_sub.setEnabled(False)
            self.list_year.setEnabled(False)

    def _cancel_subfolder_scans(self):
        """Cancel stale workers without waiting on filesystem I/O in the GUI thread."""
        self._sub_scan_generation += 1

        if self._sub_scanner is not None:
            self._sub_scanner.abort()
            self._sub_scanner = None

        for worker in tuple(self._episode_list_workers):
            worker.abort()

        for scanner in tuple(self._sub_scanner_workers):
            scanner.abort()

    def _populate_subfolders(self, base: Path):
        self._cancel_subfolder_scans()
        generation = self._sub_scan_generation
        self.list_sub.clear()

        if not is_internal_available() and self._selected_type_id() in (2, 3, 4, 7, 8):
            self.list_sub.setEnabled(False)
            return

        try:
            t = self._selected_type_id()
            year = self.list_year.current_year()

            if t == 3:
                # Enumerate episode folders in a worker first. The UI creates the buttons
                # when that result arrives, then a second worker fills each button's line 2.
                self.list_sub.show_loading_placeholder("Cargando...")
                self.list_sub.setEnabled(True)
                worker = EpisodeSubfolderListWorker(base)
                self._episode_list_workers.add(worker)
                worker.folders_ready.connect(
                    lambda paths, gen=generation, folder=base, selected_year=year:
                        self._on_episode_subfolders_ready(folder, selected_year, paths, gen)
                )
                worker.finished.connect(
                    lambda current=worker: self._episode_list_workers.discard(current)
                )
                worker.start()
                return

            if not base.is_dir():
                if t == 8:
                    self.list_sub.show_empty_placeholder(self.loc.get("menu_create_folder"))
                    self.list_sub.setEnabled(True)
                    self.subfolders_refreshed.emit()
                else:
                    self.list_sub.setEnabled(False)
                return

            subs = [
                child.name
                for child in sorted(base.iterdir(), key=lambda path: path.name.casefold())
                if child.is_dir()
            ]

            if subs:
                self.list_sub.add_subfolders(subs)
                self.list_sub.setEnabled(True)

                if t == 2:
                    self.list_sub.set_loading_placeholder("Cargando...", None, reserve_height=45)

                if t == 8:
                    if getattr(self, "_overworld_refresh_pending", False):
                        self.subfolders_refreshed.emit()
                        return

                    self._overworld_refresh_pending = True
                    self._overworld_generation += 1
                    self._overworld_client.request_overworld(
                        year=year,
                        base_path=str(base),
                        generation=self._overworld_generation,
                    )

                self.subfolders_refreshed.emit()
                return

            if t == 8:
                self.list_sub.show_empty_placeholder(self.loc.get("menu_create_folder"))
                self.list_sub.setEnabled(True)
                self.subfolders_refreshed.emit()
                return

        except Exception:
            logging.exception("Failed to populate subfolders from %s", base)

        self.list_sub.setEnabled(False)

    def _on_episode_subfolders_ready(
        self, base: Path, year: int | None, subfolder_paths: list[str], generation: int
    ):
        """Populate episode buttons first, then start the metadata scanner."""
        if generation != self._sub_scan_generation:
            return
        if self._selected_type_id() != 3 or self.list_year.current_year() != year:
            return

        if not subfolder_paths:
            self.list_sub.clear()
            self.list_sub.setEnabled(False)
            self.subfolders_refreshed.emit()
            return

        names = [Path(path).name for path in subfolder_paths]
        self.list_sub.add_subfolders(names)
        self.list_sub.setEnabled(True)
        self.list_sub.set_loading_placeholder("Cargando...", None, reserve_height=45)
        self.subfolders_refreshed.emit()

        scanner = SubfolderScanner(
            base,
            subfolders=subfolder_paths,
            cache_year=year,
        )
        self._sub_scanner = scanner
        self._sub_scanner_workers.add(scanner)
        scanner.result_ready.connect(
            lambda name, last_file, gen=generation:
                self._on_episode_subfolder_result(name, last_file, gen)
        )
        scanner.finished.connect(
            lambda current=scanner: self._on_episode_scanner_finished(current)
        )
        scanner.start()

    def _on_episode_subfolder_result(self, name: str, last_file: str, generation: int):
        if generation != self._sub_scan_generation:
            return
        if self._selected_type_id() != 3:
            return
        self.list_sub.update_button(name, last_file)

    def _on_episode_scanner_finished(self, scanner):
        self._sub_scanner_workers.discard(scanner)
        if self._sub_scanner is scanner:
            self._sub_scanner = None

    def _on_empty_create_folder_clicked(self):
        t = self._selected_type_id()
        year = self.list_year.current_year()
        if t != 8 or not year:
            return
        base = get_base_path_for_type_year(t, year)
        self._handle_create_folder(base)

    def update_subfolder_button(self, name, line2=None, line3=None):
        self.list_sub.update_button(name, line2, line3)
        
    def set_subfolders_enabled(self, enabled):
        self.list_sub.setEnabled(enabled)

    def _on_subfolder_right_clicked(self, name, pos):
        t = self._selected_type_id()
        if t in (1, 7):
            return

        year = self.list_year.current_year()
        if t in (2, 3, 4, 8) and year:
            base = get_base_path_for_type_year(t, year)
        elif t in (5, 6):
            base = get_base_path_for_docs(t)
        else:
            return

        target_folder = base / name
        if not target_folder.exists():
            return

        menu = QtWidgets.QMenu(self)
        
        act_open = menu.addAction(self.loc.get("menu_open_folder"))
        galleryanuary_path = str(getattr(config, "GALLERYANUARY_PATH", "") or "").strip()
        act_galleryanuary = None
        if galleryanuary_path:
            act_galleryanuary = menu.addAction("Abrir con GalleryAnuary")
        menu.addSeparator()
        act_move_all = menu.addAction(self.loc.get("menu_move_all_in_folder"))
        act_copy_to_folder = menu.addAction("Crear una copia para esta carpeta")

        # Dynamically add plugin UI actions targeted at directories or subfolders
        plugin_actions = []
        if self.plugin_mgr:
            buttons_def = self.plugin_mgr.get_ui_action_buttons()
            for btn_def in buttons_def:
                if btn_def.get("target") in ("directory", "subfolder"):
                    label = btn_def.get("label", "Plugin Action")
                    act = menu.addAction(label)
                    plugin_actions.append((act, btn_def["plugin_id"], btn_def.get("command")))

        act_create = menu.addAction(self.loc.get("menu_create_folder"))
        act_rename = menu.addAction(self.loc.get("menu_rename_folder"))

        state_mgr = getattr(self.window(), "state_manager", None)
        if state_mgr:
            populate_add_to_queue_menu(
                self,
                menu,
                target_folder,
                state_mgr,
                status_callback=self.status_requested.emit
            )
        
        # Only show delete if empty
        is_empty = self._is_folder_empty(target_folder)
        act_delete = None
        if is_empty:
            act_delete = menu.addAction(self.loc.get("menu_delete_folder"))

        menu.addSeparator()
        act_move_open_file = menu.addAction(self.loc.get("menu_move_and_open_file"))
        act_move_open_folder = menu.addAction(self.loc.get("menu_move_and_open_folder"))
        act_move_all_open_folder = menu.addAction(self.loc.get("menu_move_all_and_open_folder"))
        menu.addSeparator()
        act_hide_temporal = menu.addAction(self.loc.get("menu_hide_temporal"))
        menu.addSeparator()
        act_move_and_secure = menu.addAction(self.loc.get("menu_move_and_active_secure"))
        menu.addSeparator()
        act_properties = menu.addAction(self.loc.get("menu_properties"))
        act_undo = menu.addAction(self.loc.get("tray_undo"))

        action = menu.exec(pos)
        
        if action == act_open:
            os.startfile(target_folder)
        elif act_galleryanuary is not None and action == act_galleryanuary:
            self._open_with_galleryanuary(target_folder)
        elif action == act_create:
            self._handle_create_folder(base)
        elif action == act_move_all:
            self.move_all_in_folder_clicked.emit(name)
        elif action == act_copy_to_folder:
            self.copy_to_subfolder_clicked.emit(str(target_folder))
        elif action == act_rename:
            self._handle_rename_folder(target_folder)
        elif action == act_delete and act_delete:
            self._handle_delete_folder(target_folder)
        elif action == act_move_open_file:
            self.move_and_open_file_clicked.emit(name)
        elif action == act_move_open_folder:
            self.move_and_open_folder_clicked.emit(name)
        elif action == act_move_all_open_folder:
            self.move_all_and_open_folder_clicked.emit(name)
        elif action == act_hide_temporal:
            self.hide_temporal_clicked.emit()
        elif action == act_move_and_secure:
            self.move_and_enable_secure_clicked.emit(name)
        elif action == act_properties:
            self._show_folder_properties(target_folder, name)
        elif action == act_undo:
            self.undo_clicked.emit()
        else:
            # Check if action corresponds to a dynamic plugin action
            for act, plugin_id, cmd in plugin_actions:
                if action == act and cmd and self.plugin_mgr:
                    self.plugin_mgr.invoke_command(plugin_id, cmd, {"paths": [str(target_folder)]})
                    break

    def _open_with_galleryanuary(self, target_folder: Path):
        configured_path = str(getattr(config, "GALLERYANUARY_PATH", "") or "").strip()
        if not configured_path:
            return

        executable = Path(os.path.expandvars(configured_path)).expanduser()
        if not executable.is_file():
            QtWidgets.QMessageBox.warning(
                self,
                "GalleryAnuary",
                f"No se encontró el ejecutable o script configurado:\\n{executable}",
            )
            return

        command = [str(executable), str(target_folder.resolve())]
        if executable.suffix.lower() in {".py", ".pyw"}:
            command.insert(0, sys.executable)

        try:
            subprocess.Popen(command, cwd=str(executable.parent), close_fds=True)
        except Exception as exc:
            logging.exception("Error opening folder with GalleryAnuary")
            QtWidgets.QMessageBox.critical(
                self,
                "GalleryAnuary",
                f"No se pudo iniciar GalleryAnuary:\\n{exc}",
            )

    def _show_folder_properties(self, target_folder: Path, name: str):
        from folder_properties_dialog import FolderPropertiesDialog

        char_entry = None
        t = self._selected_type_id()
        year = self.list_year.current_year()
        overworld_year = year if t == 8 else None

        if t == 2 and hasattr(self.window(), "queue_panel"):
            for character in self.window().queue_panel.get_characters():
                if Path(character.path).name == name or character.path == str(target_folder):
                    char_entry = character
                    break

        dialog = FolderPropertiesDialog(
            target_folder,
            char_entry=char_entry,
            parent=self,
            loc=self.loc,
            overworld_year=overworld_year,
        )
        dialog.exec()

    def _is_folder_empty(self, path: Path) -> bool:
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.name.lower() not in ('desktop.ini', 'thumbs.db'):
                        return False
            return True
        except Exception:
            return False

    def _on_overworld_result(self, name: str, line2: str = "", line3: str = ""):
        self._overworld_refresh_pending = False
        t = self._selected_type_id()
        if t != 8:
            return

        if hasattr(self, "list_sub"):
            self.list_sub.update_button(name, line2, line3)
        
    def _handle_create_folder(self, base_path: Path):
        name, ok = QtWidgets.QInputDialog.getText(
            self, self.loc.get("dlg_create_title"), self.loc.get("dlg_create_label")
        )
        if ok and name:
            new_path = base_path / name
            try:
                new_path.mkdir(parents=True, exist_ok=True)
                self.refresh_classification_ui(force=True)
                self.folder_structure_changed.emit()
            except Exception:
                logging.exception(f"Failed to create folder: {new_path}")

    def _handle_rename_folder(self, folder_path: Path):
        name, ok = QtWidgets.QInputDialog.getText(
            self, self.loc.get("dlg_rename_title"), self.loc.get("dlg_rename_label"),
            text=folder_path.name
        )
        if ok and name and name != folder_path.name:
            new_path = folder_path.parent / name
            try:
                folder_path.rename(new_path)
                self.refresh_classification_ui(force=True)
                self.folder_structure_changed.emit()
            except Exception:
                logging.exception(f"Failed to rename folder: {folder_path} -> {new_path}")

    def _handle_delete_folder(self, folder_path: Path):
        res = QtWidgets.QMessageBox.question(
            self, self.loc.get("dlg_delete_title"), self.loc.get("dlg_delete_confirm"),
            QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No
        )
        if res == QtWidgets.QMessageBox.StandardButton.Yes:
            try:
                if delete_to_recycle_bin(folder_path):
                    self.refresh_classification_ui(force=True)
                else:
                    # Fallback to shutil if recycle bin fails for some reason
                    shutil.rmtree(folder_path)
                    self.refresh_classification_ui(force=True)
                self.folder_structure_changed.emit()
            except Exception:
                logging.exception(f"Failed to delete folder: {folder_path}")

    def set_keep_mode(self, enabled: bool):
        self.list_type.setEnabled(not enabled)
        if enabled:
            self.list_year.setEnabled(False)
            self.list_sub.setEnabled(False)
        else:
            self.refresh_classification_ui()

    def _type_icon_for(self, type_id: int) -> QIcon:
        path = self._type_icon_paths.get(type_id)
        if path:
            p = Path(path)
            if p.exists():
                return QIcon(str(p))
        return self._app_icon

    def _fill_type_list(self, selected_row: int | None = None):
        if selected_row is None:
            selected_row = self.list_type.currentRow()
        if selected_row < 0:
            # Keep the historical initial selection on Keep_downloads (type 1).
            selected_row = 1

        self.list_type.blockSignals(True)
        self.list_type.clear()

        recent_icon_path = Path(config.APP_DIR) / "assets" / "recently.png"
        recent_icon = QIcon(str(recent_icon_path)) if recent_icon_path.is_file() else self._app_icon
        recent_item = QListWidgetItem(recent_icon, "")
        recent_item.setData(QtCore.Qt.ItemDataRole.UserRole, 0)
        recent_item.setToolTip(self.loc.get("btn_recently"))
        self.list_type.addItem(recent_item)

        for type_id in range(1, 9):
            text = self.loc.get(f"type_{type_id}")
            item = QListWidgetItem(self._type_icon_for(type_id), '')
            item.setData(QtCore.Qt.ItemDataRole.UserRole, type_id)
            item.setToolTip(text)
            self.list_type.addItem(item)

        if 0 <= selected_row < self.list_type.count():
            self.list_type.setCurrentRow(selected_row)
        else:
            self.list_type.setCurrentRow(1)

        self._last_non_recent_row = (
            self.list_type.currentRow()
            if self.list_type.currentRow() > 0
            else 1
        )
        self.list_type.blockSignals(False)