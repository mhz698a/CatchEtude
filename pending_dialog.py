from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QPushButton, QVBoxLayout, QLabel
)

class PendingDialog(QtWidgets.QDialog):
    """
    Dialog shown when the window is hidden but there are still pending files.
    Diálogo que se muestra cuando la ventana se oculta pero aún hay archivos pendientes.
    """
    def __init__(self, loc_manager, on_show_clicked, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.loc = loc_manager
        self.on_show_clicked = on_show_clicked
        self._build_ui()

    def _build_ui(self):
        self.setObjectName("PendingDialog")
        self.setStyleSheet("""
            #PendingDialog {
                border: 5px solid #28a745;
                background-color: palette(window);
            }
            QLabel {
                font-weight: bold;
                font-size: 14px;
                color: palette(windowtext);
            }
            QPushButton {
                padding: 8px 16px;
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        self.lbl_msg = QLabel(self.loc.get("msg_pending_files"))
        self.lbl_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.lbl_msg)

        self.btn_show = QPushButton(self.loc.get("btn_show_again"))
        self.btn_show.clicked.connect(self.on_show_clicked)
        layout.addWidget(self.btn_show, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setFixedSize(250, 150)

    def retranslate_ui(self):
        self.lbl_msg.setText(self.loc.get("msg_pending_files"))
        self.btn_show.setText(self.loc.get("btn_show_again"))

    def showEvent(self, event):
        super().showEvent(event)
        # Center on screen
        screen = self.screen().availableGeometry()
        self.move(
            (screen.width() - self.width()) // 2,
            (screen.height() - self.height()) // 2
        )

#