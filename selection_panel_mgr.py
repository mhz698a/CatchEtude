"""
Selection panel component for CatchEtude.
Componente del panel de selección para CatchEtude.
"""

import os
import shutil
import logging
from pathlib import Path
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QHBoxLayout
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import QSize
from PyQt6.QtWidgets import QListWidgetItem

import config
from localization import LocalizationManager
from subfolder_list_mgr import SubfolderButtonList
from classification_mgr import get_base_path_for_type_year, get_base_path_for_docs, SubfolderScanner
from utils import is_internal_available, delete_to_recycle_bin
from years_selector import YearsTableWidget
from episode_cache_mgr import EpisodeCacheManager
from overworld_ipc_mgr import OverworldServiceClient

class SelectionPanel(QWidget):
    """
    Panel for selecting classification type, year, and subfolder.
    Panel para seleccionar el tipo de clasificación, año y subcarpeta.
    """
    subfolder_clicked = QtCore.pyqtSignal(str)
    subfolders_refreshed = QtCore.pyqtSignal()
    folder_structure_changed = QtCore.pyqtSignal()
    move_all_in_folder_clicked = QtCore.pyqtSignal(str)
    type_changed = QtCore.pyqtSignal(int)
    year_changed = QtCore.pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loc = LocalizationManager()
        self._app_icon = QIcon(config.ICON_PATH)
        
        self._type_icon_paths = {
            2: f"{config.APP_DIR}/assets/me-gusta.png",
            3: f"{config.APP_DIR}/assets/película.png",
            4: f"{config.APP_DIR}/assets/música.png",
            5: f"{config.APP_DIR}/assets/aula-de-google.png",
            6: f"{config.APP_DIR}/assets/identificación-verificada.png",
            7: f"{config.APP_DIR}/assets/adobe-acrobat.png",
            8: f"{config.APP_DIR}/assets/mundo.png",
        }
        
        self._sub_scanner = None
        self._overworld_client = OverworldServiceClient(self)
        self._overworld_client.result_ready.connect(self._on_overworld_result)
        self._overworld_client.finished_ready.connect(
            lambda gen: setattr(self, "_overworld_refresh_pending", False)
        )
        self._overworld_generation = 0
        self._last_loaded_type = None
        self._last_loaded_year = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
                
        # -------------------
        # Type Column
        # -------------------
        type_decition_bar = QVBoxLayout()
        type_decition_bar.setContentsMargins(110, 0, 0, 0) 
        
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
        self.list_type.setStyleSheet("""
            QListWidget {
                border: none;
                background: transparent;
                outline: none;
            }
            QListWidget::item {
                border-radius: 8px;
                padding: 4px;
            }
            QListWidget::item:hover {
                background-color: rgba(0, 120, 215, 0.1);
            }
            QListWidget::item:selected {
                background-color: rgba(0, 120, 215, 0.25);
                border: 1px solid #0078d7;
            }
            QListWidget::item:selected:focus {
                background-color: rgba(0, 120, 215, 0.25);
                border: 1px solid #0078d7;
            }
        """)
        
        type_decition_bar.addWidget(self.list_type)
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
        self.list_year.setStyleSheet("""
            QTableWidget {
                border: none;
                background: transparent;
            }
            QTableWidget::item {
                border-radius: 4px;
                padding: 4px;
            }
            QTableWidget::item:selected {
                background-color: #0078d7;
                color: white;
            }
        """)
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
        self.list_sub.clicked.connect(self.subfolder_clicked.emit)
        self.list_sub.rightClicked.connect(self._on_subfolder_right_clicked)
        self.list_sub.emptyCreateClicked.connect(self._on_empty_create_folder_clicked)
        v_sub.addWidget(self.list_sub)
        
        bottom_h_row.addLayout(v_sub)
        layout.addLayout(bottom_h_row)
        

    def retranslate_ui(self):               
        curr = self.list_type.currentRow()
        self._fill_type_list(curr)

    def _on_type_changed(self, idx):
        self.type_changed.emit(idx + 2)
        self.refresh_classification_ui()

    def _on_year_changed(self, year):
        if year >= 0:
            self.year_changed.emit(year)
            self.refresh_classification_ui()
                
    def get_selection(self):
        return {
            'type': self.list_type.currentRow() + 2,
            'year': self.list_year.current_year()
        }

    def refresh_classification_ui(self, force=False):
        t = self.list_type.currentRow() + 2
        year = self.list_year.current_year() if t in (2, 3, 4, 8) else None

        if not force and t == self._last_loaded_type and year == self._last_loaded_year:
            if t in (2, 3, 4, 8):
                if year:
                    self.list_year.setEnabled(True)
                    self.list_sub.setEnabled(True)
                else:
                    self.list_sub.setEnabled(False)
            elif t in (5, 6):
                self.list_sub.setEnabled(True)
                self.list_year.setEnabled(False)
            else:
                self.list_sub.setEnabled(False)
                self.list_year.setEnabled(False)
            return

        self._last_loaded_type = t
        self._last_loaded_year = year

        if t in (2, 3, 4, 8):
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

    def _populate_subfolders(self, base: Path):
        self.list_sub.clear()
        
        if self._sub_scanner:
            self._sub_scanner.abort()
            self._sub_scanner.wait()
            self._sub_scanner = None

        if not is_internal_available() and (self.list_type.currentRow() + 2) in (2, 3, 4, 7, 8):
            self.list_sub.setEnabled(False)
            return

        try:
            t = self.list_type.currentRow() + 2
            subs = []
            
            if base.exists() and base.is_dir():
                subs = [c.name for c in sorted(base.iterdir()) if c.is_dir()]
            else:
                return
                
            if subs:
                self.list_sub.add_subfolders(subs)
                self.list_sub.setEnabled(True)

                if t == 2:
                    self.list_sub.set_loading_placeholder("Cargando...", "Cargando...", reserve_height=60)
                if t == 3:
                    self.list_sub.set_loading_placeholder("Cargando...", None, reserve_height=45)
                elif t == 8:
                    self.list_sub.set_loading_placeholder("Cargando...", "Cargando...", reserve_height=60)
                                
                                
                if t == 3: # Episodes
                    self._sub_scanner = SubfolderScanner(base, EpisodeCacheManager(self.list_year.current_year()))
                    self._sub_scanner.result_ready.connect(
                        lambda name, ffile: self.list_sub.update_button(name, ffile)
                    )
                    self._sub_scanner.start()
                    
                elif t == 8:
                    if hasattr(self, "_overworld_refresh_pending"):
                        if self._overworld_refresh_pending:
                            return

                    self._overworld_refresh_pending = True

                    self._overworld_generation += 1
                    self.list_sub.set_loading_placeholder("Cargando...", "Cargando...", reserve_height=60)

                    self._overworld_client.request_overworld(
                        year=self.list_year.current_year(),
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
            logging.exception(f"Failed to populate subfolders from {base}")

        self.list_sub.setEnabled(False)

    def _on_empty_create_folder_clicked(self):
        t = self.list_type.currentRow() + 2
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
        t = self.list_type.currentRow() + 2
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
        menu.addSeparator()
        act_move_all = menu.addAction(self.loc.get("menu_move_all_in_folder"))
        act_create = menu.addAction(self.loc.get("menu_create_folder"))
        act_rename = menu.addAction(self.loc.get("menu_rename_folder"))
        
        # Only show delete if empty
        is_empty = self._is_folder_empty(target_folder)
        act_delete = None
        if is_empty:
            act_delete = menu.addAction(self.loc.get("menu_delete_folder"))

        action = menu.exec(pos)
        
        if action == act_open:
            os.startfile(target_folder)
        elif action == act_create:
            self._handle_create_folder(base)
        elif action == act_move_all:
            self.move_all_in_folder_clicked.emit(name)
        elif action == act_rename:
            self._handle_rename_folder(target_folder)
        elif action == act_delete and act_delete:
            self._handle_delete_folder(target_folder)

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
        t = self.list_type.currentRow() + 2
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

        self.list_type.blockSignals(True)
        self.list_type.clear()

        for type_id in range(2, 9):
            text = self.loc.get(f"type_{type_id}")
            item = QListWidgetItem(self._type_icon_for(type_id), '')
            item.setData(QtCore.Qt.ItemDataRole.UserRole, type_id)
            item.setToolTip(text)
            self.list_type.addItem(item)

        if 0 <= selected_row < self.list_type.count():
            self.list_type.setCurrentRow(selected_row)
        else:
            self.list_type.setCurrentRow(0)

        self.list_type.blockSignals(False)