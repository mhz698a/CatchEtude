from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QPushButton, QVBoxLayout, QLabel
)
from ui_utils_mgr import load_stylesheet

class PendingDialog(QtWidgets.QDialog):
    """
    Dialog shown when the window is hidden but there are still pending files.
    Diálogo que se muestra cuando la ventana se oculta pero aún hay archivos pendientes.
    """
    def __init__(self, loc_manager, on_show_clicked, parent=None):
        super().__init__(parent, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.loc = loc_manager
        self.on_show_clicked = on_show_clicked
        self._pending_count = 0
        
        # Ajusta la opacidad (0.0 = totalmente transparente, 1.0 = completamente opaco)
        self.setWindowOpacity(0.85)
        
        self._build_ui()

    def _build_ui(self):
        self.setObjectName("PendingDialog")
        self.setStyleSheet(load_stylesheet("pending_dialog.css"))
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        self.lbl_msg = QLabel()
        self.lbl_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_msg.setWordWrap(True)
        layout.addWidget(self.lbl_msg)
        self.set_pending_count(self._pending_count)

        self.btn_show = QPushButton(self.loc.get("btn_show_again"))
        self.btn_show.clicked.connect(self.on_show_clicked)
        layout.addWidget(self.btn_show, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setFixedSize(250, 150)

    def set_pending_count(self, count: int) -> None:
        self._pending_count = max(0, int(count))
        template = self.loc.get("msg_pending_files_count")
        self.lbl_msg.setText(template.format(count=self._pending_count))

    def retranslate_ui(self):
        self.set_pending_count(self._pending_count)
        self.btn_show.setText(self.loc.get("btn_show_again"))

    def showEvent(self, event):
        super().showEvent(event)
        CENTER = False
        screen = self.screen().availableGeometry()
        margin = 20
        if CENTER:
            self.move(
                (screen.width() - self.width()) // 2,
                (screen.height() - self.height()) // 2
            )
        else:
            self.move(
                screen.x() + screen.width() - self.width() - margin,
                screen.y() + screen.height() - self.height() - margin
            )
            