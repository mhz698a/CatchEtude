"""
Selection panel component for CatchEtude.
Componente del panel de selección para CatchEtude.
"""

import logging
from pathlib import Path
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget

from config import YEARS, ONEDRIVE_DOCS, ONEDRIVE_DOCTOS_FAMILIA
from localization import LocalizationManager
from subfolder_list_mgr import SubfolderButtonList
from classification_mgr import get_base_path_for_type_year, get_base_path_for_docs, SubfolderScanner
from utils import is_internal_available

class SelectionPanel(QWidget):
    """
    Panel for selecting classification type, year, and subfolder.
    Panel para seleccionar el tipo de clasificación, año y subcarpeta.
    """
    subfolder_clicked = QtCore.pyqtSignal(str)
    subfolders_refreshed = QtCore.pyqtSignal()
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

        top_row = QHBoxLayout()

        # Type Column
        v_type = QVBoxLayout()
        self.lbl_type = QLabel(self.loc.get("lbl_type"))
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

        # Subfolder Column
        v_sub = QVBoxLayout()
        self.lbl_sub = QLabel(self.loc.get("lbl_subfolders"))
        v_sub.addWidget(self.lbl_sub)
        self.list_sub = SubfolderButtonList()
        self.list_sub.setEnabled(False)
        self.list_sub.clicked.connect(self.subfolder_clicked.emit)
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
        self.list_type.addItems([self.loc.get(f"type_{i}") for i in range(1, 9)])
        self.list_type.setCurrentRow(curr)
        self.list_type.blockSignals(False)

    def _on_type_changed(self, idx):
        self.type_changed.emit(idx + 1)
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
            'type': self.list_type.currentRow() + 1,
            'year': int(item_year.text()) if item_year else None
        }

    def refresh_classification_ui(self):
        t = self.list_type.currentRow() + 1
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

        if not is_internal_available() and (self.list_type.currentRow() + 1) in (2, 3, 4, 7, 8):
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
