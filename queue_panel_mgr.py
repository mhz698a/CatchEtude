"""
Queue and character panel component for CatchEtude.
Componente del panel de cola y personajes para CatchEtude.
"""

from pathlib import Path
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QListWidget
from PyQt6.QtCore import Qt

from localization import LocalizationManager
from ui_utils_mgr import QueueDelegate
from character_mgr import CharacterListModel

class QueuePanel(QWidget):
    """
    Panel for showing the download queue and managing character data.
    Panel para mostrar la cola de descargas y gestionar los datos de personajes.
    """
    characters_updated = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loc = LocalizationManager()
        self._build_ui()

    def _build_ui(self):
        self.setFixedWidth(380)
        layout = QVBoxLayout(self)

        # Download Queue
        self.lbl_queue = QLabel(self.loc.get("lbl_queue"))
        layout.addWidget(self.lbl_queue)

        self.queue_list_widget = QListWidget()
        self.queue_list_widget.setItemDelegate(QueueDelegate(self))
        self.queue_list_widget.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        layout.addWidget(self.queue_list_widget)

        # Character Model
        self.char_model = CharacterListModel()
        self.char_model.modelReset.connect(self.characters_updated.emit)
        self.char_model.dataChanged.connect(self.characters_updated.emit)

    def retranslate_ui(self):
        self.lbl_queue.setText(self.loc.get("lbl_queue"))

    def update_queue(self, queue_list: list[Path], active_path_str: str):
        """Updates the download queue UI list."""
        self.queue_list_widget.clear()
        for p in queue_list:
            item = QtWidgets.QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            item.setData(Qt.ItemDataRole.UserRole + 1, str(p) == active_path_str)
            self.queue_list_widget.addItem(item)

    def request_characters(self, year: int, generation: int):
        self.char_model.clear_data()
        self.char_model.request_characters(year, generation)

    def get_characters(self):
        return self.char_model.items
