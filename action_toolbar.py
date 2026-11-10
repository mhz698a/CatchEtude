from PyQt6 import QtCore, QtWidgets
from PyQt6.QtWidgets import QToolBar
from PyQt6.QtCore import Qt

from localization import LocalizationManager
from drag_label_widget import DragLabel

class ActionToolBar(QToolBar):
    """
    Barra de herramientas superior que contiene el DragLabel, 
    la acción de recarga y las acciones principales de archivo.
    """
    reload_clicked = QtCore.pyqtSignal()
    open_clicked = QtCore.pyqtSignal()
    delete_clicked = QtCore.pyqtSignal()
    flat_folder_clicked = QtCore.pyqtSignal()
    edit_metadata_clicked = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Action ToolBar", parent)
        self.loc = LocalizationManager()
        self._build_ui()

    def _build_ui(self):
        self.setMovable(False)
        self.setFloatable(False)
        self.setObjectName("ActionToolBar")
        
        self.setStyleSheet("QToolButton { height: 30px; }")

        # 1. Widget de arrastre (DragLabel)
        self.drag_icon = DragLabel()
        self.drag_icon.setEnabled(False)
        self.addWidget(self.drag_icon)

        self.addSeparator()

        # 2. Acciones nativas de la barra
        self.action_reload = self.addAction(self.loc.get("btn_reload"))
        self.action_reload.setToolTip(self.loc.get("tooltip_reload"))
        self.action_reload.triggered.connect(self.reload_clicked.emit)

        self.action_open = self.addAction(self.loc.get("btn_open"))
        self.action_open.triggered.connect(self.open_clicked.emit)

        self.action_delete = self.addAction(self.loc.get("btn_header_delete"))
        self.action_delete.triggered.connect(self.delete_clicked.emit)

        self.action_flat_folder = self.addAction("Flat Folder")
        self.action_flat_folder.triggered.connect(self.flat_folder_clicked.emit)
        self.action_flat_folder.setVisible(False)

        self.action_edit_metadata = self.addAction("Edit metadata")
        self.action_edit_metadata.triggered.connect(self.edit_metadata_clicked.emit)
        self.action_edit_metadata.setVisible(False)

    def retranslate_ui(self):
        self.action_reload.setText(self.loc.get("btn_reload"))
        self.action_reload.setToolTip(self.loc.get("tooltip_reload"))
        self.action_open.setText(self.loc.get("btn_open"))
        self.action_delete.setText(self.loc.get("btn_header_delete"))
        self.action_flat_folder.setText("Flat Folder")
        self.action_edit_metadata.setText("Edit metadata")

    def set_file(self, p):
        if self.drag_icon:
            self.drag_icon.set_file(p)

    def clear(self):
        if self.drag_icon:
            self.drag_icon.set_file(None)