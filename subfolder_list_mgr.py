"""
Module for managing a list of buttons for fast file movement.
Módulo para gestionar una lista de botones para el movimiento rápido de archivos.
"""

from PyQt6 import QtWidgets, QtCore

class SubfolderButton(QtWidgets.QPushButton):
    """
    A custom button that can display up to three lines of text with different styles.
    Botón personalizado que puede mostrar hasta tres líneas de texto con diferentes estilos.
    """
    rightClicked = QtCore.pyqtSignal(str, QtCore.QPoint)

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        self.setToolTip(name)
        
        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(8, 2, 8, 2)
        self._layout.setSpacing(0)
        self._layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignVCenter)
        
        self.lbl_name = QtWidgets.QLabel(name)
        self.lbl_name.setStyleSheet("font-weight: normal; background: transparent; border: none;")
        self.lbl_name.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._layout.addWidget(self.lbl_name)
        
        self.lbl_extra1 = QtWidgets.QLabel("")
        self.lbl_extra1.setStyleSheet("font-style: italic; background: transparent; border: none;")
        self.lbl_extra1.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_extra1.hide()
        self._layout.addWidget(self.lbl_extra1)
        
        self.lbl_extra2 = QtWidgets.QLabel("")
        self.lbl_extra2.setStyleSheet("color: gray; background: transparent; border: none;")
        self.lbl_extra2.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_extra2.hide()
        self._layout.addWidget(self.lbl_extra2)
        
        self.setFixedHeight(30)
        self.setStyleSheet("QPushButton { text-align: left; }")

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            self.rightClicked.emit(self.name, event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def set_data(self, line2=None, line3=None):
        """
        Updates the button with extra lines of information.
        Actualiza el botón con líneas adicionales de información.
        """
        if line2:
            self.lbl_extra1.setText(line2)
            self.lbl_extra1.show()
        else:
            self.lbl_extra1.hide()
            
        if line3:
            self.lbl_extra2.setText(line3)
            self.lbl_extra2.show()
        else:
            self.lbl_extra2.hide()
            
        # Adjust height based on content
        if line2 and line3:
            self.setFixedHeight(60)
        elif line2 or line3:
            self.setFixedHeight(45)
        else:
            self.setFixedHeight(30)

class SubfolderButtonList(QtWidgets.QScrollArea):
    """
    A widget that displays a list of buttons, one for each subfolder.
    Un widget que muestra una lista de botones, uno para cada subcarpeta.
    """
    clicked = QtCore.pyqtSignal(str)
    rightClicked = QtCore.pyqtSignal(str, QtCore.QPoint)

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
        self._buttons = {} # name -> SubfolderButton

    def clear(self):
        """Removes all buttons from the list."""
        while self.layout.count() > 1: # Keep the stretch
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._buttons = {}

    def add_subfolders(self, subfolders: list[str]):
        """Adds a button for each subfolder in the list."""
        self.clear()
        # Add buttons before the stretch
        for name in subfolders:
            btn = SubfolderButton(name)
            # Use a lambda with a default argument to capture the current name
            btn.clicked.connect(lambda checked, n=name: self.clicked.emit(n))
            btn.rightClicked.connect(lambda n, pos: self.rightClicked.emit(n, pos))
            self.layout.insertWidget(self.layout.count() - 1, btn)
            self._buttons[name] = btn
        
        self.setEnabled(self._enabled)

    def update_button(self, name: str, line2=None, line3=None):
        """Updates a specific button by folder name."""
        if name in self._buttons:
            self._buttons[name].set_data(line2, line3)

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
        
        # Restore scroll position
        vbar.setValue(scroll_pos)
