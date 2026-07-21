import logging
import sys
import ctypes
from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, QFormLayout, QScrollArea, QWidget
)
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt
import config

class SettingsDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Ajustes - {config.APP_NAME}")
        self.setWindowIcon(QIcon(config.ICON_PATH))
        self.setMinimumWidth(800)
        
        self.settings = config.load_settings()
        self.inputs = {}
        
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        form_layout = QFormLayout(scroll_content)
        
        for key in config.DEFAULT_SETTINGS.keys():
            value = self.settings.get(key, config.DEFAULT_SETTINGS[key])
            line_edit = QLineEdit(str(value))
            form_layout.addRow(QLabel(key), line_edit)
            self.inputs[key] = line_edit
            
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        buttons_layout = QHBoxLayout()
        btn_save = QPushButton("Guardar")
        btn_save.clicked.connect(self.save)
        btn_discard = QPushButton("Descartar")
        btn_discard.clicked.connect(self.reject)
        
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_save)
        buttons_layout.addWidget(btn_discard)
        layout.addLayout(buttons_layout)
        
    def save(self):
        new_settings = {}
        for key, line_edit in self.inputs.items():
            value = line_edit.text()
            # Try to preserve types (int for BLUR_LEVEL)
            if isinstance(config.DEFAULT_SETTINGS[key], int):
                try:
                    value = int(value)
                except ValueError:
                    logging.debug("Int Value is not int value")
            elif isinstance(config.DEFAULT_SETTINGS[key], bool):
                value = (value.strip().lower() == "true")
            new_settings[key] = value
            
        config.save_settings(new_settings)
        self.accept()

def main():
    try:
        # Use the same MYAPPID to group with the main application and share the icon
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(config.MYAPPID)
    except OSError as e:
        logging.debug(f"Failed to set AppUserModelID (Windows integration): {e}")
    except Exception as e:
        logging.debug(f"Unexpected error setting AppUserModelID: {e}")
    
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(config.ICON_PATH))
    dialog = SettingsDialog()
    dialog.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
