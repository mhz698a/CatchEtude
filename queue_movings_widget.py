"""
Queue Movings Widget module for CatchEtude.
Módulo Queue Movings Widget para CatchEtude.
"""

from pathlib import Path
from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt

class MovingItemWidget(QWidget):
    """
    Custom widget for each item in the queue_movings list.
    Displays the filename on top, and a QProgressBar below.
    """
    def __init__(self, filename: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        self.lbl_name = QLabel(filename)
        self.lbl_name.setStyleSheet("font-weight: bold; font-size: 11px;")
        self.lbl_name.setWordWrap(True)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #777;
                border-radius: 2px;
                text-align: center;
                font-size: 9px;
            }
            QProgressBar::chunk {
                background-color: #26a69a;
            }
        """)

        layout.addWidget(self.lbl_name)
        layout.addWidget(self.progress_bar)


class QueueMovingsWidget(QListWidget):
    """
    List widget managing pending movements.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._items_map = {}  # Maps src Path to (QListWidgetItem, MovingItemWidget)

    def add_movement(self, src: Path, dst: Path):
        """Adds a new background move entry."""
        # Ensure we don't duplicate
        if src in self._items_map:
            return

        item = QListWidgetItem(self)
        item.setSizeHint(QtCore.QSize(200, 50))

        widget = MovingItemWidget(dst.name, self)
        self.addItem(item)
        self.setItemWidget(item, widget)

        self._items_map[src] = (item, widget)

    def update_progress(self, src: Path, value: int):
        """Updates progress for a specific move."""
        if src in self._items_map:
            _, widget = self._items_map[src]
            widget.progress_bar.setValue(value)

    def remove_movement(self, src: Path):
        """Removes a finished background move entry."""
        if src in self._items_map:
            item, _ = self._items_map.pop(src)
            row = self.row(item)
            if row >= 0:
                self.takeItem(row)
