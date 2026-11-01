# NG: Newgrounds dialog para obtener informacion segun el ID 
try:
    import pywinstyles
except ImportError:
    pywinstyles = None
import webbrowser
from PyQt6 import QtWidgets, QtGui
from pyrenameutils.ng_extract import extract_ng, NGError

class NewgroundsDialog(QtWidgets.QDialog):
    def __init__(self, idsong, parent=None):
        super().__init__(parent)
        self.idsong = idsong
        self.result_data = None
        self.init_ui()

    def init_ui(self):
        try:
            if pywinstyles:
                pywinstyles.change_header_color(self, color="#232629")
        except Exception:
            pass
        
        self.setWindowTitle("Newgrounds metadata")
        self.setModal(True)
        self.setFixedSize(360, 220)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(10)

        self.id_edit = QtWidgets.QLineEdit()
        self.id_edit.setPlaceholderText("Audio ID (numeric)")
        self.id_edit.setFixedHeight(34)
        
        if self.idsong and self.idsong.isdigit():
            self.id_edit.setText(self.idsong)

        self.chk_title = QtWidgets.QCheckBox("Title")
        self.chk_artist = QtWidgets.QCheckBox("Artist")
        self.chk_filename = QtWidgets.QCheckBox("Filename")
        self.chk_title.setChecked(True)
        self.chk_artist.setChecked(True)
        self.chk_filename.setChecked(True)

        chk_layout = QtWidgets.QHBoxLayout()
        chk_layout.addWidget(self.chk_title)
        chk_layout.addWidget(self.chk_artist)
        chk_layout.addWidget(self.chk_filename)

        btn_get = QtWidgets.QPushButton("Get")
        btn_acc = QtWidgets.QPushButton("Go to")
        btn_cancel = QtWidgets.QPushButton("Cancel")
        btn_get.setFixedWidth(100)
        btn_acc.setFixedWidth(100)
        btn_cancel.setFixedWidth(100)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(btn_get)
        btn_layout.addWidget(btn_acc)
        btn_layout.addWidget(btn_cancel)

        layout.addWidget(QtWidgets.QLabel("Newgrounds Audio ID:"))
        layout.addWidget(self.id_edit)
        layout.addLayout(chk_layout)
        layout.addStretch()
        layout.addLayout(btn_layout)

        btn_cancel.clicked.connect(self.reject)
        btn_acc.clicked.connect(self.on_goto_page)
        btn_get.clicked.connect(self.on_get_clicked)

    def on_goto_page(self):
        webbrowser.open("https://newgrounds.com/audio/listen/" + self.id_edit.text())

    def on_get_clicked(self):
        song_id = self.id_edit.text().strip()
        if not song_id.isdigit():
            QtWidgets.QMessageBox.warning(self, "Error", "ID inválido.")
            return

        try:
            data = extract_ng(song_id)
        except NGError as e:
            QtWidgets.QMessageBox.critical(self, "Newgrounds error", str(e))
            return
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"Fallo inesperado:\n{e}")
            return

        self.result_data = {
            "title": data.get("title") if self.chk_title.isChecked() else None,
            "artist": data.get("artist") if self.chk_artist.isChecked() else None,
            "filename": data.get("title") if self.chk_filename.isChecked() else None,
            "ng_id": song_id
        }
        self.accept()