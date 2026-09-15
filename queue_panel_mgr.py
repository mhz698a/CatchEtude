"""
Queue and character panel component for CatchEtude.
Componente del panel de cola y personajes para CatchEtude.
"""

from pathlib import Path
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton, QSizePolicy
from PyQt6.QtCore import Qt

from localization import LocalizationManager
from ui_utils_mgr import QueueDelegate
from character_mgr import CharacterListModel
from queue_movings_widget import QueueMovingsWidget

MAX_VISIBLE_DOWNLOAD_QUEUE_ITEMS = 200

class QueuePanel(QWidget):
    """
    Panel for showing the download queue and managing character data.
    Panel para mostrar la cola de descargas y gestionar los datos de personajes.
    """
    characters_updated = QtCore.pyqtSignal()
    character_updated = QtCore.pyqtSignal(object)
    file_double_clicked = QtCore.pyqtSignal(str)
    movings_minimized_changed = QtCore.pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.loc = LocalizationManager()
        self._hide_secure = False
        self._queue_pending = 0
        self._queue_total = 0
        self._queue_non_shown = 0
        self._movings_minimized = False
        self._build_ui()

    def _build_ui(self):
        self.setFixedWidth(380)
        layout = QVBoxLayout(self)
        
        # Download Queue
        self.lbl_queue = QLabel()
        self._refresh_queue_label()
        layout.addWidget(self.lbl_queue)
        
        self.queue_list_widget = QListWidget()
        self.queue_list_widget.setItemDelegate(QueueDelegate(self))
        self.queue_list_widget.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.queue_list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.queue_list_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self.queue_list_widget, 1)

        # Pending Movements Row (Label + Minimize Button)
        movings_header_row = QHBoxLayout()
        movings_header_row.setContentsMargins(0, 0, 0, 0)

        self.lbl_movings = QLabel()
        self.lbl_movings.setText(self.loc.get("lbl_queue_movings"))
        movings_header_row.addWidget(self.lbl_movings)
        movings_header_row.addStretch()

        self.btn_toggle_movings = QPushButton("▲")
        self.btn_toggle_movings.setFixedSize(24, 20)
        self.btn_toggle_movings.setToolTip("Ocultar/Mostrar movimientos pendientes")
        self.btn_toggle_movings.clicked.connect(self.toggle_movings_minimized)
        movings_header_row.addWidget(self.btn_toggle_movings)

        layout.addLayout(movings_header_row)

        self.queue_movings_widget = QueueMovingsWidget(self)
        self.queue_movings_widget.setMaximumHeight(200)
        layout.addWidget(self.queue_movings_widget)

        # Global Progress Bar
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        # Character Model
        self.char_model = CharacterListModel()
        self.char_model.modelReset.connect(self.characters_updated.emit)
        self.char_model.dataChanged.connect(self._on_char_data_changed)

    def _on_item_double_clicked(self, item: QtWidgets.QListWidgetItem):
        path_str = item.data(Qt.ItemDataRole.UserRole)
        is_active = item.data(Qt.ItemDataRole.UserRole + 1)
        if path_str and not is_active:
            self.file_double_clicked.emit(path_str)

    def toggle_movings_minimized(self):
        self.set_movings_minimized(not self._movings_minimized)

    def set_movings_minimized(self, minimized: bool):
        self._movings_minimized = minimized
        if minimized:
            self.queue_movings_widget.hide()
            self.btn_toggle_movings.setText("▼")
        else:
            self.queue_movings_widget.show()
            self.btn_toggle_movings.setText("▲")
        self.movings_minimized_changed.emit(minimized)

    def is_movings_minimized(self) -> bool:
        return self._movings_minimized

    def _on_char_data_changed(self, topLeft, bottomRight, roles=None):
        for row in range(topLeft.row(), bottomRight.row() + 1):
            if 0 <= row < len(self.char_model.items):
                char_entry = self.char_model.items[row]
                self.character_updated.emit(char_entry)

    def retranslate_ui(self):
        self._refresh_queue_label()
        if hasattr(self, 'lbl_movings'):
            self.lbl_movings.setText(self.loc.get("lbl_queue_movings"))

    def set_progress(self, val: int):
        self.progress.setValue(val)

    def set_hide_secure(self, enabled: bool):
        self._hide_secure = enabled
        self.queue_list_widget.itemDelegate().set_hide_secure(enabled)
        self.queue_list_widget.viewport().update()

    def update_queue(self, queue_list: list[Path], active_path_str: str):
        """Updates the download queue UI list."""
        self.queue_list_widget.clear()
        total = len(queue_list)
        pending = sum(1 for p in queue_list if str(p) != active_path_str)
        visible_queue = queue_list[:MAX_VISIBLE_DOWNLOAD_QUEUE_ITEMS]
        non_shown = max(0, total - len(visible_queue))
        self._refresh_queue_label(pending, total, non_shown)
        
        for p in visible_queue:
            item = QtWidgets.QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            item.setData(Qt.ItemDataRole.UserRole + 1, str(p) == active_path_str)
            self.queue_list_widget.addItem(item)

    def request_characters(self, year: int, generation: int):
        self.char_model.clear_data()
        self.char_model.request_characters(year, generation)

    def get_characters(self):
        return self.char_model.items

    def _refresh_queue_label(
        self,
        pending: int | None = None,
        total: int | None = None,
        non_shown: int | None = None,
    ):
        if pending is not None:
            self._queue_pending = pending
        if total is not None:
            self._queue_total = total
        if non_shown is not None:
            self._queue_non_shown = non_shown

        # {self._queue_pending:02d}/
        self.lbl_queue.setText(
            f"{self.loc.get('lbl_queue')} - Left: {self._queue_total:02d} "
            f"- Non show: {self._queue_non_shown:02d}"
        )
