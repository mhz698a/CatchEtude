QSS = """
QWidget {
    background-color: #1e1e1e;
    color: #dddddd;
    font-size: 11pt;
}
QLineEdit, QComboBox {
    background-color: #2b2b2b;
    border: 1px solid #3c3c3c;
    padding: 6px;
}
QComboBox QAbstractItemView {
    background-color: #2b2b2b;
    border: 1px solid #3c3c3c;
    color: #ffffff;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 30px; /* Incrementa este valor para un botón más ancho */
}
QPushButton {
    background-color: #333333;
    border: 1px solid #444444;
    padding: 6px 14px;
}
QPushButton:hover {
    background-color: #3d3d3d;
}
QPushButton:pressed {
    background-color: #2a2a2a;
}
QCheckBox {
    padding: 4px;
}
QLabel {
    padding-bottom: 4px;
}
"""