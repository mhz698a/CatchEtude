"""
Selection panel component for CatchEtude.
Componente del panel de selección para CatchEtude.
"""

import os
import shutil
import logging
from pathlib import Path
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget

from config import YEARS, ONEDRIVE_DOCS, ONEDRIVE_DOCTOS_FAMILIA
from localization import LocalizationManager
from subfolder_list_mgr import SubfolderButtonList
from classification_mgr import get_base_path_for_type_year, get_base_path_for_docs, SubfolderScanner
from utils import is_internal_available, delete_to_recycle_bin

class SelectionPanel(QWidget):
    """
    Panel for selecting classification type, year, and subfolder.
    Panel para seleccionar el tipo de clasificación, año y subcarpeta.
    """
    subfolder_clicked = QtCore.pyqtSignal(str)
    subfolders_refreshed = QtCore.pyqtSignal()
    folder_structure_changed = QtCore.pyqtSignal()
    type_changed = QtCore.pyqtSignal(int)
    year_changed = QtCore.pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loc = LocalizationManager()
        self._sub_scanner = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # ==========================
        # Fila de Desicion y Años
        # ==========================
        top_row = QHBoxLayout()
        
        # Type Column
        v_type = QVBoxLayout()
        self.lbl_type = QLabel(self.loc.get("lbl_type"))
        v_type.addWidget(self.lbl_type)
        
        self.list_type = QListWidget()
        self.list_type.addItems([self.loc.get(f"type_{i}") for i in range(2, 9)])
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
            QListWidget::item { border-radius: 4px; }
            QListWidget::item:selected { background-color: #0078d7; color: white; }
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
        
        # ==========================
        # Fila de las subcarpetas
        # ==========================

        # Subfolder Column
        v_sub = QVBoxLayout()
        self.lbl_sub = QLabel(self.loc.get("lbl_subfolders"))
        v_sub.addWidget(self.lbl_sub)
        self.list_sub = SubfolderButtonList()
        self.list_sub.setEnabled(False)
        self.list_sub.clicked.connect(self.subfolder_clicked.emit)
        self.list_sub.rightClicked.connect(self._on_subfolder_right_clicked)
        v_sub.addWidget(self.list_sub)
        
        layout.addLayout(top_row)
        layout.addLayout(v_sub)

    def retranslate_ui(self):
        self.lbl_type.setText(self.loc.get("lbl_type"))
        self.lbl_year.setText(self.loc.get("lbl_years"))
        self.lbl_sub.setText(self.loc.get("lbl_subfolders"))
        
        curr = self.list_type.currentRow()
        self.list_type.blockSignals(True)
        self.list_type.clear()
        self.list_type.addItems([self.loc.get(f"type_{i}") for i in range(2, 9)])
        if 0 <= curr < self.list_type.count():
            self.list_type.setCurrentRow(curr)
        else:
            self.list_type.setCurrentRow(0)
        # self.list_type.setCurrentRow(curr)
        self.list_type.blockSignals(False)

    def _on_type_changed(self, idx):
        self.type_changed.emit(idx + 2)
        self.refresh_classification_ui()

    def _on_year_changed(self, idx):
        if idx >= 0:
            item = self.list_year.item(idx)
            if item:
                self.year_changed.emit(int(item.text()))
        self.refresh_classification_ui()

    def get_selection(self):
        item_year = self.list_year.currentItem()
        return {
            'type': self.list_type.currentRow() + 2,
            'year': int(item_year.text()) if item_year else None
        }

    def refresh_classification_ui(self):
        t = self.list_type.currentRow() + 2
        if t in (2, 3, 4, 8):
            item = self.list_year.currentItem()
            if item:
                year = int(item.text())
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
            if base.exists() and base.is_dir():
                subs = [c.name for c in sorted(base.iterdir()) if c.is_dir()]
                if subs:
                    self.list_sub.add_subfolders(subs)
                    self.list_sub.setEnabled(True)
                    
                    t = self.list_type.currentRow() + 1
                    if t == 3: # Episodes
                        self._sub_scanner = SubfolderScanner(base)
                        self._sub_scanner.result_ready.connect(
                            lambda name, ffile: self.list_sub.update_button(name, ffile)
                        )
                        self._sub_scanner.start()
                    
                    self.subfolders_refreshed.emit()
                    return
        except Exception:
            logging.exception(f"Failed to populate subfolders from {base}")

        self.list_sub.setEnabled(False)

    def update_subfolder_button(self, name, line2=None, line3=None):
        self.list_sub.update_button(name, line2, line3)
        
    def set_subfolders_enabled(self, enabled):
        self.list_sub.setEnabled(enabled)

    def _on_subfolder_right_clicked(self, name, pos):
        t = self.list_type.currentRow() + 1
        item = self.list_year.currentItem()
        year = int(item.text()) if item else None
        
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

    def _handle_create_folder(self, base_path: Path):
        name, ok = QtWidgets.QInputDialog.getText(
            self, self.loc.get("dlg_create_title"), self.loc.get("dlg_create_label")
        )
        if ok and name:
            new_path = base_path / name
            try:
                new_path.mkdir(parents=True, exist_ok=True)
                self.refresh_classification_ui()
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
                self.refresh_classification_ui()
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
                    self.refresh_classification_ui()
                else:
                    # Fallback to shutil if recycle bin fails for some reason
                    shutil.rmtree(folder_path)
                    self.refresh_classification_ui()
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

