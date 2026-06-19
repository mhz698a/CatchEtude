from math import ceil

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem, QAbstractItemView


class YearsTableWidget(QTableWidget):
    yearChanged = QtCore.pyqtSignal(int)

    def __init__(self, years, parent=None):
        super().__init__(0, 0, parent)
        self._years = list(years)
        self._min_cell_w = 40
        self._cell_h = 28
        self._selected_year = 2004 if 2004 in self._years else (self._years[0] if self._years else None)

        self.setShowGrid(False)
        self.horizontalHeader().hide()
        self.verticalHeader().hide()
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)

        self.itemSelectionChanged.connect(self._emit_year_changed)
        self._rebuild()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild()

    def current_year(self):
        item = self.currentItem()
        return int(item.text()) if item else None

    def _emit_year_changed(self):
        year = self.current_year()
        if year is not None:
            self.yearChanged.emit(year)

    def _rebuild(self):
        if not self._years:
            self.clearContents()
            self.setRowCount(0)
            self.setColumnCount(0)
            return

        current = self.current_year() or self._selected_year
        width = max(1, self.viewport().width())

        cols = max(1, width // self._min_cell_w)
        cols = min(cols, len(self._years))
        rows = ceil(len(self._years) / cols)

        self.blockSignals(True)
        self.clearContents()
        self.setRowCount(rows)
        self.setColumnCount(cols)

        col_w = max(self._min_cell_w, width // cols)
        for c in range(cols):
            self.setColumnWidth(c, col_w)

        for r in range(rows):
            self.setRowHeight(r, self._cell_h)

        for i, year in enumerate(self._years):
            r, c = divmod(i, cols)
            item = QTableWidgetItem(str(year))
            item.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.setItem(r, c, item)

        self.blockSignals(False)
        self._select_year(current)

    def _select_year(self, year):
        if year is None:
            return
        for r in range(self.rowCount()):
            for c in range(self.columnCount()):
                item = self.item(r, c)
                if item and int(item.text()) == year:
                    self.setCurrentItem(item)
                    return