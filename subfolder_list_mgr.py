"""
Module for managing a list of buttons for fast file movement.
Módulo para gestionar una lista de botones para el movimiento rápido de archivos.
"""

from PyQt6 import QtWidgets, QtCore

class SubfolderButtonList(QtWidgets.QScrollArea):
    """
    A widget that displays a list of buttons, one for each subfolder.
    Un widget que muestra una lista de botones, uno para cada subcarpeta.
    """
    clicked = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.container = QtWidgets.QWidget()
        self.layout = QtWidgets.QVBoxLayout(self.container)
        self.layout.setContentsMargins(2, 2, 2, 2)
        self.layout.setSpacing(2)
        self.layout.addStretch()
        self.setWidget(self.container)
        self._enabled = True

    def clear(self):
        """Removes all buttons from the list."""
        while self.layout.count() > 1: # Keep the stretch
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def add_subfolders(self, subfolders: list[str]):
        """Adds a button for each subfolder in the list."""
        self.clear()
        # Add buttons before the stretch
        for name in subfolders:
            btn = QtWidgets.QPushButton(name)
            btn.setFixedHeight(30)
            btn.setStyleSheet("text-align: left; padding-left: 8px;")
            btn.setToolTip(name)
            # Use a lambda with a default argument to capture the current name
            btn.clicked.connect(lambda checked, n=name: self.clicked.emit(n))
            self.layout.insertWidget(self.layout.count() - 1, btn)
        
        self.setEnabled(self._enabled)

    def setEnabled(self, enabled: bool):
        self._enabled = enabled
        
        # Save current scroll position
        vbar = self.verticalScrollBar()
        scroll_pos = vbar.value()
        
        # Update all buttons
        for i in range(self.layout.count()):
            item = self.layout.itemAt(i)
            if item.widget():
                item.widget().setEnabled(enabled)
        
        super().setEnabled(enabled)
        
        # Restore scroll position after a short delay to ensure layout updates don't override it
        # However, a synchronous restore might be enough if super().setEnabled doesn't trigger async layout.
        vbar.setValue(scroll_pos)
