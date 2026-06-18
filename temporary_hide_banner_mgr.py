from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QPushButton, QHBoxLayout, QSizePolicy


class TemporaryHideBanner(QtWidgets.QWidget):
    show_again_clicked = QtCore.pyqtSignal()
    timeout_reached = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._remaining = 0
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._build_ui()

    def _build_ui(self):
        self.setObjectName("TemporaryHideBanner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMinimumWidth(560)
        self.setFixedHeight(66)
        self.setStyleSheet("""
            #TemporaryHideBanner {
                background: #fff9c4;
                border: 2px solid #fbc02d;
                /*border-radius: 8px;*/
            }
            QLabel {
                color: #3b2f00;
                font-weight: 600;
            }
            QPushButton {
                background: #ffeb3b;
                border: 1px solid #c9a400;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 700;
                color: #000;
            }
            QPushButton:hover {
                background: #ffe066;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(12)

        self.lbl_msg = QLabel("")
        self.lbl_msg.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        self.btn_show = QPushButton("Show Again")
        self.btn_show.clicked.connect(self._on_show_again)

        layout.addWidget(self.lbl_msg, 1)
        layout.addWidget(self.btn_show, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

    def start(self, seconds: int = 5):
        self._remaining = max(1, int(seconds))
        self._update_text()
        self._position_bottom()
        self.show()
        self.raise_()
        self.activateWindow()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def _update_text(self):
        self.lbl_msg.setText(
            f"CatchEtude aparecera de nuevo en {self._remaining} segundos ..."
        )

    def _tick(self):
        self._remaining -= 1
        if self._remaining <= 0:
            self.stop()
            self.timeout_reached.emit()
            return
        self._update_text()

    def _on_show_again(self):
        self.stop()
        self.show_again_clicked.emit()

    def _position_bottom(self):
        screen = self.screen() or QtWidgets.QApplication.primaryScreen()
        if screen is None:
            return

        geo = screen.availableGeometry()
        self.adjustSize()

        target_width = min(
            max(self.sizeHint().width(), 560),
            max(320, geo.width() - 40),
        )
        self.resize(target_width, self.height())

        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + geo.height() - self.height() - 12
        self.move(x, y)

    def showEvent(self, event):
        super().showEvent(event)
        self._position_bottom()