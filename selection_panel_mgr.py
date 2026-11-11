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
from classification_mgr import EpisodeSubfolderListWorker, SubfolderScanner
from utils import is_internal_available, delete_to_recycle_bin
from years_selector import YearsTableWidget
from episode_cache_mgr import EpisodeCacheManager
from overworld_ipc_mgr import OverworldServiceClient
from subfolder_queue_addmore import populate_add_to_queue_menu
from ui_utils_mgr import load_stylesheet
from classification_registry import ClassificationRegistry
from decision_dispatcher import DecisionDispatcher

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
        self.classification_registry = ClassificationRegistry()
        self.decision_dispatcher = DecisionDispatcher(self, self.classification_registry)
        
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
        


    def on_classification_registry_changed(self):
        """Refresh the selection panel after the registry has been saved."""
        selected_type_id = self._selected_type_id()
        existing_ids = {
            decision["id"] for decision in self.classification_registry.decisions
        }
        self._recent_subfolders = [
            recent for recent in self._recent_subfolders
            if recent.get("type") in existing_ids
        ]
        self._recent_items_by_label = {}
        self._last_loaded_type = None
        self._last_loaded_year = None
        self._cancel_subfolder_scans()
        self._fill_type_list(selected_type_id)
        refreshed_type_id = self._selected_type_id()

        if refreshed_type_id == 0:
            self._populate_recent_subfolders()
        elif refreshed_type_id != selected_type_id:
            # Mirror a normal type selection so MainWindow can refresh any
            # type-specific services (for example character metadata).
            self._on_type_changed(self.list_type.currentRow())
        else:
            self.refresh_classification_ui(force=True)

    def retranslate_ui(self):
        selected_type_id = self._selected_type_id()
        self._fill_type_list(selected_type_id)
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
        if self._selected_type_id() == 0:
            recent = self._recent_items_by_label.get(name)
            if recent is not None:
                self._choose_recent_subfolder(recent)
            return
        decision = self.get_current_decision()
        if decision is not None:
            self.decision_dispatcher.dispatch_subfolder_click(decision, name)

    def _remember_recent_subfolder(self, name: str):
        decision = self.get_current_decision()
        if not decision or not name or decision.get("folder_source") == "none":
            return
        needs_year = self.decision_dispatcher.requires_year(decision)
        year = self.list_year.current_year() if needs_year else None
        if needs_year and year is None:
            return
        type_id = decision["id"]
        recent = {"type": type_id, "year": year, "name": name}
        self._recent_subfolders = [
            item for item in self._recent_subfolders
            if not (item.get("type") == type_id and item.get("year") == year and item.get("name") == name)
        ]
        self._recent_subfolders.insert(0, recent)
        del self._recent_subfolders[20:]

    def _recent_subfolder_label(self, recent: dict) -> str:
        type_id = recent.get("type")
        decision = self.classification_registry.get_decision(type_id)
        type_label = (
            self.classification_registry.get_decision_name(decision, self.loc.current_lang(), self.loc)
            if decision else f"type_{type_id}"
        )
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
        type_id, year, name = recent.get("type"), recent.get("year"), recent.get("name")
        decision = self.classification_registry.get_decision(type_id)
        if not decision or not decision.get("enabled", True) or decision.get("folder_source") == "none" or not name:
            return
        needs_year = self.decision_dispatcher.requires_year(decision)
        if needs_year and year is None:
            return
        target_row = None
        for row in range(1, self.list_type.count()):
            item = self.list_type.item(row)
            if item and item.data(QtCore.Qt.ItemDataRole.UserRole) == type_id:
                target_row = row
                break
        if target_row is None:
            return
        self.list_type.setCurrentRow(target_row)
        self._last_non_recent_type_id = type_id
        if year is not None:
            if year in getattr(config, "NONCANON_YEARS", ()):
                self.list_year._select_hidden_year(year)
            else:
                self.list_year._select_year(year)
        self._on_subfolder_clicked(name)

    def _on_type_changed(self, idx):
        if idx < 0:
            return
        type_id = self._selected_type_id()
        if type_id == 0:
            self._populate_recent_subfolders()
            return
        decision = self.classification_registry.get_decision(type_id)
        if decision is None:
            self.list_sub.clear()
            self.list_sub.setEnabled(False)
            self.list_year.setEnabled(False)
            return
        self._last_non_recent_type_id = type_id
        self._cancel_subfolder_scans()
        self.type_changed.emit(type_id)
        self.refresh_classification_ui()
    def _on_year_changed(self, year):
        if year >= 0:
            self.year_changed.emit(year)
            self.refresh_classification_ui()


    def get_current_decision(self):
        type_id = self._selected_type_id()
        if type_id == 0:
            type_id = getattr(self, "_last_non_recent_type_id", None)
        return self.classification_registry.get_decision(type_id)

    def get_selection(self):
        type_id = self._selected_type_id()
        if type_id == 0:
            type_id = getattr(self, "_last_non_recent_type_id", None)
            if type_id is None:
                active = self.classification_registry.get_active_decisions()
                type_id = active[0]["id"] if active else 1
        decision = self.classification_registry.get_decision(type_id)
        year = self.list_year.current_year() if decision and self.decision_dispatcher.requires_year(decision) else None
        return {"type": type_id, "year": year}

    def refresh_classification_ui(self, force=False):
        decision = self.get_current_decision()
        if decision is None:
            self.list_sub.clear()
            self.list_sub.setEnabled(False)
            self.list_year.setEnabled(False)
            return
        type_id = decision["id"]
        handler = decision.get("handler")
        needs_year = self.decision_dispatcher.requires_year(decision)
        year = self.list_year.current_year() if needs_year else None
        if not force and type_id == self._last_loaded_type and year == self._last_loaded_year:
            self.list_year.setEnabled(needs_year)
            self.list_sub.setEnabled(not needs_year or year is not None)
            return
        self._last_loaded_type, self._last_loaded_year = type_id, year

        if handler == "keep":
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
            return
        if handler == "linear_docs":
            self.list_sub.add_subfolders(["Guardar en el año seleccionado","Guardar en el año actual"])
            self.list_sub.setEnabled(True)
            self.list_year.setEnabled(True)
            return
        if handler != "move_to_subfolder" or decision.get("folder_source") == "none":
            self.list_sub.clear()
            self.list_sub.setEnabled(False)
            self.list_year.setEnabled(False)
            return
        self.list_year.setEnabled(needs_year)
        if needs_year and year is None:
            self.list_sub.clear()
            self.list_sub.setEnabled(False)
            return
        base = self.decision_dispatcher.resolve_base_path(decision, year)
        self._populate_subfolders(base, decision)
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


    def _populate_subfolders(self, base: Path | None, decision: dict | None = None):
        self._cancel_subfolder_scans()
        generation = self._sub_scan_generation
        self.list_sub.clear()
        if base is None:
            self.list_sub.setEnabled(False)
            return
        decision = decision or self.get_current_decision()
        if decision is None:
            self.list_sub.setEnabled(False)
            return
        if self.decision_dispatcher.requires_internal(decision) and not is_internal_available():
            self.list_sub.setEnabled(False)
            return

        type_id = decision["id"]
        needs_year = self.decision_dispatcher.requires_year(decision)
        year = self.list_year.current_year() if needs_year else None
        secondary = decision.get("behaviour_second_line")
        try:
            if secondary == "last_file":
                self.list_sub.show_loading_placeholder("Cargando...")
                self.list_sub.setEnabled(True)
                worker = EpisodeSubfolderListWorker(base)
                self._episode_list_workers.add(worker)
                worker.folders_ready.connect(
                    lambda paths, gen=generation, folder=base, selected_year=year, selected_type=type_id:
                        self._on_background_subfolders_ready(folder, selected_year, paths, gen, selected_type)
                )
                worker.finished.connect(lambda current=worker: self._episode_list_workers.discard(current))
                worker.start()
                return

            if not base.is_dir():
                if decision.get("allow_create", False):
                    self.list_sub.show_empty_placeholder(self.loc.get("menu_create_folder"))
                    self.list_sub.setEnabled(True)
                    self.subfolders_refreshed.emit()
                else:
                    self.list_sub.setEnabled(False)
                return

            subs = [
                child.name for child in sorted(base.iterdir(), key=lambda p:p.name.casefold())
                if child.is_dir()
            ]
            if subs:
                self.list_sub.add_subfolders(subs)
                self.list_sub.setEnabled(True)
                if secondary == "character_metadata":
                    self.list_sub.set_loading_placeholder("Cargando...", None, reserve_height=45)
                if secondary == "overworld_metadata":
                    if getattr(self, "_overworld_refresh_pending", False):
                        self.subfolders_refreshed.emit()
                        return
                    self._overworld_refresh_pending = True
                    self._overworld_generation += 1
                    self._overworld_client.request_overworld(
                        year=year, base_path=str(base), generation=self._overworld_generation
                    )
                self.subfolders_refreshed.emit()
                return
            if decision.get("allow_create", False):
                self.list_sub.show_empty_placeholder(self.loc.get("menu_create_folder"))
                self.list_sub.setEnabled(True)
                self.subfolders_refreshed.emit()
                return
        except Exception:
            logging.exception("Failed to populate subfolders from %s", base)
        self.list_sub.setEnabled(False)

    def _on_background_subfolders_ready(self, base: Path, year: int | None, subfolder_paths: list[str], generation: int, decision_id: int):
        """Populate folders first, then scan declared secondary-line metadata."""
        if generation != self._sub_scan_generation:
            return
        decision = self.classification_registry.get_decision(decision_id)
        selected_year = self.list_year.current_year() if decision and self.decision_dispatcher.requires_year(decision) else None
        if self._selected_type_id() != decision_id or selected_year != year or not decision or decision.get("behaviour_second_line") != "last_file":
            return
        if not subfolder_paths:
            self.list_sub.clear()
            if decision.get("allow_create", False):
                self.list_sub.show_empty_placeholder(self.loc.get("menu_create_folder"))
                self.list_sub.setEnabled(True)
            else:
                self.list_sub.setEnabled(False)
            self.subfolders_refreshed.emit()
            return
        self.list_sub.add_subfolders([Path(p).name for p in subfolder_paths])
        self.list_sub.setEnabled(True)
        self.list_sub.set_loading_placeholder("Cargando...", None, reserve_height=45)
        self.subfolders_refreshed.emit()
        scanner = SubfolderScanner(base, subfolders=subfolder_paths, cache_year=year)
        self._sub_scanner = scanner
        self._sub_scanner_workers.add(scanner)
        scanner.result_ready.connect(
            lambda name, secondary, gen=generation, selected_type=decision_id:
                self._on_background_subfolder_result(name, secondary, gen, selected_type)
        )
        scanner.finished.connect(lambda current=scanner: self._on_episode_scanner_finished(current))
        scanner.start()

    def _on_background_subfolder_result(self, name: str, secondary_text: str, generation: int, decision_id: int):
        if generation != self._sub_scan_generation:
            return
        decision = self.classification_registry.get_decision(decision_id)
        if self._selected_type_id() != decision_id or not decision or decision.get("behaviour_second_line") != "last_file":
            return
        self.list_sub.update_button(name, secondary_text)
    def _on_episode_scanner_finished(self, scanner):
        self._sub_scanner_workers.discard(scanner)
        if self._sub_scanner is scanner:
            self._sub_scanner = None


    def _on_empty_create_folder_clicked(self):
        decision = self.get_current_decision()
        if not decision or not decision.get("allow_create", False):
            return
        needs_year = self.decision_dispatcher.requires_year(decision)
        year = self.list_year.current_year() if needs_year else None
        if needs_year and year is None:
            return
        base = self.decision_dispatcher.resolve_base_path(decision, year)
        if base is not None:
            self._handle_create_folder(base)
    def update_subfolder_button(self, name, line2=None, line3=None):
        self.list_sub.update_button(name, line2, line3)
        
    def set_subfolders_enabled(self, enabled):
        self.list_sub.setEnabled(enabled)


    def _on_subfolder_right_clicked(self, name, pos):
        if self._selected_type_id() == 0:
            return
        decision = self.get_current_decision()
        if not decision or decision.get("folder_source") == "none" or not decision.get("context_menu", True):
            return
        needs_year = self.decision_dispatcher.requires_year(decision)
        year = self.list_year.current_year() if needs_year else None
        if needs_year and year is None:
            return
        base = self.decision_dispatcher.resolve_base_path(decision, year)
        if base is None or Path(name).name != name:
            return
        target_folder = base / name
        if not target_folder.is_dir():
            return

        menu = QtWidgets.QMenu(self)
        act_open = menu.addAction(self.loc.get("menu_open_folder"))
        galleryanuary_path = str(getattr(config, "GALLERYANUARY_PATH", "") or "").strip()
        act_galleryanuary = menu.addAction("Abrir con GalleryAnuary") if galleryanuary_path else None
        menu.addSeparator()
        act_move_all = menu.addAction(self.loc.get("menu_move_all_in_folder"))
        act_copy_to_folder = menu.addAction("Crear una copia para esta carpeta")
        plugin_actions = []
        if self.plugin_mgr:
            for btn_def in self.plugin_mgr.get_ui_action_buttons():
                if btn_def.get("target") in ("directory", "subfolder"):
                    a = menu.addAction(btn_def.get("label", "Plugin Action"))
                    plugin_actions.append((a, btn_def["plugin_id"], btn_def.get("command")))

        act_create = menu.addAction(self.loc.get("menu_create_folder")) if decision.get("allow_create", False) else None
        act_rename = menu.addAction(self.loc.get("menu_rename_folder")) if decision.get("allow_rename", False) else None
        state_mgr = getattr(self.window(), "state_manager", None)
        if state_mgr:
            populate_add_to_queue_menu(self, menu, target_folder, state_mgr, status_callback=self.status_requested.emit)
        act_delete = None
        if decision.get("allow_delete", False) and self._is_folder_empty(target_folder):
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
        elif act_create is not None and action == act_create:
            self._handle_create_folder(base)
        elif action == act_move_all:
            self.move_all_in_folder_clicked.emit(name)
        elif action == act_copy_to_folder:
            self.copy_to_subfolder_clicked.emit(str(target_folder))
        elif act_rename is not None and action == act_rename:
            self._handle_rename_folder(target_folder)
        elif act_delete is not None and action == act_delete:
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
            for plugin_action, plugin_id, command in plugin_actions:
                if action == plugin_action and command and self.plugin_mgr:
                    self.plugin_mgr.invoke_command(plugin_id, command, {"paths": [str(target_folder)]})
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
        decision = self.get_current_decision() or {}
        secondary = decision.get("behaviour_second_line")
        year = self.list_year.current_year()
        overworld_year = year if secondary == "overworld_metadata" else None
        char_entry = None
        if secondary == "character_metadata" and hasattr(self.window(), "queue_panel"):
            for character in self.window().queue_panel.get_characters():
                if Path(character.path).name == name or character.path == str(target_folder):
                    char_entry = character
                    break
        dialog = FolderPropertiesDialog(target_folder,char_entry=char_entry,parent=self,loc=self.loc,overworld_year=overworld_year)
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
        decision = self.get_current_decision()
        if not decision or decision.get("behaviour_second_line") != "overworld_metadata":
            return
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


    def _type_icon_for(self, decision: dict) -> QIcon:
        icon_name = decision.get("icon")
        if icon_name:
            path = Path(config.APP_DIR) / "assets" / str(icon_name)
            if path.is_file():
                return QIcon(str(path))
        return self._app_icon

    def _fill_type_list(self, selected_type_id: int | None = None):
        active = self.classification_registry.get_active_decisions()
        active_ids = {d["id"] for d in active}
        if selected_type_id is None and self.list_type.currentRow() >= 0:
            selected_type_id = self._selected_type_id()
        if selected_type_id is None:
            selected_type_id = active[0]["id"] if active else 0
        if selected_type_id not in active_ids and selected_type_id != 0:
            selected_type_id = active[0]["id"] if active else 0

        recent_path = Path(config.APP_DIR) / "assets" / "recently.png"
        recent_icon = QIcon(str(recent_path)) if recent_path.is_file() else self._app_icon
        self.list_type.blockSignals(True)
        self.list_type.clear()
        recent = QListWidgetItem(recent_icon, "")
        recent.setData(QtCore.Qt.ItemDataRole.UserRole, 0)
        recent.setToolTip(self.loc.get("btn_recently"))
        self.list_type.addItem(recent)

        selected_row = 0 if selected_type_id == 0 else None
        for decision in active:
            type_id = decision["id"]
            label = self.classification_registry.get_decision_name(decision,self.loc.current_lang(),self.loc)
            item = QListWidgetItem(self._type_icon_for(decision), "")
            item.setData(QtCore.Qt.ItemDataRole.UserRole, type_id)
            item.setToolTip(label)
            self.list_type.addItem(item)
            if type_id == selected_type_id:
                selected_row = self.list_type.count()-1

        if selected_row is None:
            selected_row = 1 if self.list_type.count()>1 else 0
        self.list_type.setCurrentRow(selected_row)
        if selected_type_id in active_ids:
            self._last_non_recent_type_id = selected_type_id
        elif getattr(self, "_last_non_recent_type_id", None) not in active_ids:
            self._last_non_recent_type_id = active[0]["id"] if active else None
        self.list_type.blockSignals(False)
