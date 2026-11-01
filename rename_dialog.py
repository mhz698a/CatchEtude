# rename_dialog.py
import ctypes
try:
    import pywinstyles
except ImportError:
    pywinstyles = None
import re, sys, os
from pathlib import Path
from PyQt6 import QtWidgets, QtGui
from PyQt6.QtCore import Qt, pyqtSignal, QBuffer, QIODevice
from pyrenameutils.qss_styles import QSS
from pyrenameutils.ng_dialog import NewgroundsDialog
from pyrenameutils.helpers_text import sanitize_windows_filename
from pyrenameutils.helpers_tags import read_tags, write_tags
from pyrenameutils.helpers_win import set_creation_and_modification_windows, es_solo_lectura_windows, wait_until_file_unlocked, can_write_file, is_file_in_use
from pyrenameutils.helpers_cover import read_cover_art, write_cover_art, write_cover_art_data, export_cover_art


APP_DIR = Path(__file__).resolve().parent.as_posix()
ICON_WIN = f"{APP_DIR}/assets/catchetude-icon.png"
myappid = 'etudetools.files_mgr.rename_dialog.1.0'
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

class CoverLabel(QtWidgets.QLabel):
    clicked = pyqtSignal()
    rightClicked = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._has_cover = False
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(180, 180)
        self.setFixedSize(180, 180)
        self.setStyleSheet("""
            QLabel {
                border: 1px solid #444444;
                background-color: #232323;
                color: #dddddd;
            }
        """)
        self.setText("Agregar Carátula")

    def set_has_cover(self, has_cover: bool):
        self._has_cover = has_cover
        if not has_cover:
            self.setText("Agregar Carátula")

    def enterEvent(self, event):
        if not self._has_cover:
            self.setText("<u>Agregar Carátula</u>")
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self._has_cover:
            self.setText("Agregar Carátula")
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        elif event.button() == Qt.MouseButton.RightButton:
            self.rightClicked.emit(event.globalPosition().toPoint())
        super().mousePressEvent(event)

class RenameDialog(QtWidgets.QWidget):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.file_path = os.path.abspath(file_path)
        self.dir_path = os.path.dirname(self.file_path)
        self.base_name = os.path.basename(self.file_path)
        self.name, self.ext = os.path.splitext(self.base_name)
        self.is_mp4 = self.ext.lower() in ('.mp4', '.m4a', '.m4v')
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Rename file")
        flags = self.windowFlags()
        flags &= ~Qt.WindowType.WindowMaximizeButtonHint
        self.setWindowFlags(flags)

        self.setFixedSize(700, 920)
        try:
            if pywinstyles:
                pywinstyles.change_header_color(self, color="#232629")
        except Exception:
            pass

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(8)
        
        # Newgrounds
        self.ng_btn = QtWidgets.QPushButton("Newgrounds")
        self.ng_btn.setFixedHeight(36)
        self.ng_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.ng_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.ng_btn.clicked.connect(self.open_ng_dialog)

        header_layout = QtWidgets.QHBoxLayout()
        header_layout.addWidget(QtWidgets.QLabel("New name:"))
        header_layout.addStretch()
        header_layout.addWidget(self.ng_btn)

        main_layout.addLayout(header_layout)
        
        # File name
        self.edit = QtWidgets.QLineEdit(self.name)
        self.edit.setPlaceholderText("File name (without extension)")

        # Transform buttons
        transforms_layout = QtWidgets.QHBoxLayout()
        transforms_layout.setSpacing(6)
        btn_underscores = QtWidgets.QPushButton("'_' → ' '")
        btn_guions = QtWidgets.QPushButton("'-' → ' '")
        btn_sentence = QtWidgets.QPushButton("Abcd")
        btn_lower = QtWidgets.QPushButton("abcd")
        btn_upper = QtWidgets.QPushButton("ABCD")
        btn_title = QtWidgets.QPushButton("Ab Cd")
        btn_append_eta = QtWidgets.QPushButton("(η)")
        
        transforms = [btn_underscores, btn_guions, btn_sentence, btn_lower, btn_upper, btn_title, btn_append_eta]
        for b in transforms:
            b.setFixedHeight(34)
            transforms_layout.addWidget(b)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        # Metadata fields
        meta_layout = QtWidgets.QFormLayout()
        meta_layout.setSpacing(6)
        meta_layout.setVerticalSpacing(8)

        self.title_edit = QtWidgets.QLineEdit()
        self.artist_edit = QtWidgets.QLineEdit()
        self.album_edit = QtWidgets.QLineEdit()
        self.year_edit = QtWidgets.QLineEdit()
        self.date_edit = QtWidgets.QLineEdit()
        self.track_edit = QtWidgets.QLineEdit()
        self.disc_edit = QtWidgets.QLineEdit()
        self.comment_edit = QtWidgets.QTextEdit()
        self.comment_edit.setFixedHeight(160)
        
        self.genre_choices = ["", "Episode", "Movie", "Short", "Soundtrack"]

        self.genre_line = QtWidgets.QLineEdit()
        self.genre_combo = QtWidgets.QComboBox()
        self.genre_combo.addItems(self.genre_choices)
        self.genre_combo.setEditable(False)

        self.genre_stack = QtWidgets.QStackedWidget()
        self.genre_stack.addWidget(self.genre_line)   # index 0
        self.genre_stack.addWidget(self.genre_combo)  # index 1

        self.genre_line.setFixedHeight(38)
        self.genre_combo.setFixedHeight(38)

        self.title_id_btn = QtWidgets.QPushButton("(ID:)")
        self.title_id_btn.setFixedWidth(90)
        self.title_id_btn.setFixedHeight(38)
        self.title_id_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.title_id_btn.setToolTip("Añadir (ID:) al final del título")

        self.title_paste_btn = QtWidgets.QPushButton("[ T ]")
        self.title_paste_btn.setFixedWidth(90)
        self.title_paste_btn.setFixedHeight(38)
        self.title_paste_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.title_paste_btn.setToolTip("Mover el título al campo de título")

        title_layout = QtWidgets.QHBoxLayout()
        title_layout.setSpacing(4)
        title_layout.addWidget(self.title_edit)
        title_layout.addWidget(self.title_id_btn)
        title_layout.addWidget(self.title_paste_btn)

        self.artist_paste_btn = QtWidgets.QPushButton("[ A ]")
        self.artist_paste_btn.setFixedWidth(90)
        self.artist_paste_btn.setFixedHeight(38)
        self.artist_paste_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.artist_paste_btn.setToolTip("Mover el artista al campo de artistas")
        
        self.cover_label = CoverLabel()
        self.cover_label.clicked.connect(self.replace_cover_from_dialog)
        self.cover_label.rightClicked.connect(self.show_cover_context_menu)

        artist_layout = QtWidgets.QHBoxLayout()
        artist_layout.setSpacing(4)
        artist_layout.addWidget(self.artist_edit)
        artist_layout.addWidget(self.artist_paste_btn)

        self.album_edit.setFixedHeight(38)
        self.year_edit.setFixedHeight(38)
        self.date_edit.setFixedHeight(38)
        self.track_edit.setFixedHeight(38)
        self.disc_edit.setFixedHeight(38)
        self.genre_line.setFixedHeight(38)
        self.genre_combo.setFixedHeight(38)
        self.title_edit.setFixedHeight(38)
        self.artist_edit.setFixedHeight(38)

        self.year_edit.setPlaceholderText("YYYY")
        self.date_edit.setPlaceholderText("YYYY-MM-DD o YYYY-MM-DDTHH:MM:SSZ")
        self.track_edit.setPlaceholderText("00 o 00/00")
        self.disc_edit.setPlaceholderText("00/00, 000/000 o 00/000")

        self.year_label = QtWidgets.QLabel("Year:")
        self.date_label = QtWidgets.QLabel("Date:")
        self.disc_label = QtWidgets.QLabel("Disc:")

        self.year_label.setEnabled(not self.is_mp4)
        self.year_edit.setEnabled(not self.is_mp4)

        meta_layout.addRow(QtWidgets.QLabel("Title:"), title_layout)
        meta_layout.addRow(QtWidgets.QLabel("Artist:"), artist_layout)
        meta_layout.addRow(QtWidgets.QLabel("Album:"), self.album_edit)
        meta_layout.addRow(self.year_label, self.year_edit)
        meta_layout.addRow(self.date_label, self.date_edit)
        meta_layout.addRow(QtWidgets.QLabel("Track:"), self.track_edit)
        meta_layout.addRow(self.disc_label, self.disc_edit)
        meta_layout.addRow(QtWidgets.QLabel("Genre:"), self.genre_stack)

        cover_widget = QtWidgets.QWidget()
        cover_layout = QtWidgets.QHBoxLayout(cover_widget)
        cover_layout.setContentsMargins(0, 0, 0, 0)
        cover_layout.addWidget(self.cover_label)
        cover_layout.addStretch()
        meta_layout.addRow(QtWidgets.QLabel("Cover:"), cover_widget)
        meta_layout.addRow(QtWidgets.QLabel("Comment:"), self.comment_edit)
        
        
        # Footer: checkbox + single Rename button + Close
        footer_layout = QtWidgets.QHBoxLayout()
        footer_layout.setSpacing(8)
        
        self.always_on_top_checkbox = QtWidgets.QCheckBox("Siempre visible")
        self.always_on_top_checkbox.setChecked(True)
        self.always_on_top_checkbox.stateChanged.connect(self.on_always_on_top_changed)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        
        self.overwrite_checkbox = QtWidgets.QCheckBox("Es Sobrescritor")
        self.overwrite_checkbox.setChecked(False)
        self.overwrite_checkbox.stateChanged.connect(self.sync_genre_mode)

        footer_buttons_layout = QtWidgets.QHBoxLayout()
        footer_buttons_layout.setSpacing(6)
        
        btn_rename = QtWidgets.QPushButton("Rename") # único botón que aplica etiquetas y renombra
        btn_close = QtWidgets.QPushButton("Close")
        btn_rename.setFixedWidth(140)
        btn_close.setFixedWidth(100)
        footer_buttons_layout.addWidget(btn_rename)
        footer_buttons_layout.addWidget(btn_close)

        footer_layout.addWidget(self.always_on_top_checkbox)
        footer_layout.addWidget(self.overwrite_checkbox)
        footer_layout.addStretch()
        footer_layout.addLayout(footer_buttons_layout)

        # Connect signals
        btn_underscores.clicked.connect(self.replace_underscores)
        btn_guions.clicked.connect(self.remplace_guiones)
        btn_sentence.clicked.connect(self.to_sentence_case)
        btn_lower.clicked.connect(self.to_lowercase)
        btn_upper.clicked.connect(self.to_uppercase)
        btn_title.clicked.connect(self.to_title_case)
        btn_append_eta.clicked.connect(self.append_eta)

        btn_rename.clicked.connect(self.on_rename_clicked)
        btn_close.clicked.connect(self.close)
        
        # Tags Connect signals
        self.title_id_btn.clicked.connect(self.append_title_id)
        self.title_paste_btn.clicked.connect(self.move_title_filename_to_title)
        self.artist_paste_btn.clicked.connect(self.move_artist_filename_to_artist)

        # Compose main layout
        main_layout.addWidget(self.edit)
        main_layout.addLayout(transforms_layout)
        main_layout.addLayout(meta_layout)
        main_layout.addStretch()
        main_layout.addLayout(footer_layout)

        self.apply_dark_theme()
        self.center_on_screen()

        # Load existing tags into fields (best-effort)
        try:
            tags = read_tags(self.file_path)
            self.title_edit.setText(tags.get('title', '') or '')
            self.artist_edit.setText(tags.get('artist', '') or '')
            self.album_edit.setText(tags.get('album', '') or '')
            self.year_edit.setText(tags.get('year', '') or '')
            self.date_edit.setText(tags.get('date', '') or '')
            self.track_edit.setText(tags.get('track', '') or '')
            self.disc_edit.setText(tags.get('disc', '') or '')
            genre_value = tags.get('genre', '') or ''
            self.set_genre_value(genre_value)
            self.sync_genre_mode()
            self.comment_edit.setText(tags.get('comment', '') or '')
            self.load_cover_art()
        except Exception:
            pass

    def center_on_screen(self):
        screen = QtWidgets.QApplication.primaryScreen().availableGeometry()
        geo = self.frameGeometry()
        geo.moveCenter(screen.center())
        self.move(geo.topLeft())

    def apply_dark_theme(self):
        self.setStyleSheet(QSS)

    # New functions in 2026-06-08
    def get_genre_value(self):
        if self.overwrite_checkbox.isChecked():
            return self.genre_combo.currentText().strip()
        return self.genre_line.text().strip()

    def set_genre_value(self, value: str):
        value = (value or "").strip()

        if value in self.genre_choices:
            self.genre_combo.setCurrentText(value)
        else:
            self.genre_combo.setCurrentIndex(0)

        self.genre_line.setText(value)

    def sync_genre_mode(self, *_):
        strict = self.overwrite_checkbox.isChecked()
        current = self.get_genre_value()

        if strict:
            self.genre_stack.setCurrentWidget(self.genre_combo)
            self.genre_combo.setCurrentText(
                current if current in self.genre_choices else ""
            )
        else:
            self.genre_stack.setCurrentWidget(self.genre_line)
            self.genre_line.setText(current)

    def validate_metadata_fields(self):
        year = self.year_edit.text().strip()
        date = self.date_edit.text().strip()
        disc = self.disc_edit.text().strip()

        # if date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2}Z?)?", date):
        #     QtWidgets.QMessageBox.warning(
        #         self,
        #         "Fecha inválida",
        #         "Usa YYYY-MM-DD o YYYY-MM-DDTHH:MM:SSZ."
        #     )
        #     return None

        if self.is_mp4:
            year = ""
        elif year and not re.fullmatch(r"\d{4}", year):
            QtWidgets.QMessageBox.warning(self, "Year inválido", "Usa YYYY.")
            return None

        if disc and not re.fullmatch(r"\d{2}(?:/\d{2})?", disc):
            QtWidgets.QMessageBox.warning(
                self,
                "Disc inválido",
                "Formatos válidos: 00/00, 000/000 o 00/000."
            )
            return None

        return year, date, disc

    # Transformations
    def replace_underscores(self):
        text = self.edit.text()
        new = ' '.join(text.replace("(_)", "").replace("_", " ").strip().split())
        self.edit.setText(new)
        
    def remplace_guiones(self):
        text = self.edit.text()
        new = ' '.join(text.replace("(_)", "").replace("-", " ").strip().split())
        self.edit.setText(new)

    def to_sentence_case(self):
        text = self.edit.text().strip()
        if not text:
            return
        lowered = text.replace("_", " ").lower()
        for i, ch in enumerate(lowered):
            if ch.isalpha():
                new = lowered[:i] + lowered[i].upper() + lowered[i+1:]
                self.edit.setText(new)
                return
        self.edit.setText(lowered)

    def to_lowercase(self):
        text = self.edit.text()
        self.edit.setText(text.replace("_", " ").lower())

    def to_uppercase(self):
        text = self.edit.text()
        self.edit.setText(text.replace("_", " ").upper())

    def to_title_case(self):
        text = self.edit.text()
        self.edit.setText(text.replace("_", " ").title())

    def append_eta(self):
        text = self.edit.text()
        
        if text.endswith("integerNG"):
            self.edit.setText(text.replace(" integerNG", "").replace("_integerNG", "") + " (η)")
            return
        
        if text.endswith(" (η)"):
            return
        self.edit.setText(text + " (η)")

    def on_always_on_top_changed(self, state):
        checked = self.always_on_top_checkbox.isChecked()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, checked)
        flags = self.windowFlags()
        flags &= ~Qt.WindowType.WindowMaximizeButtonHint
        self.setWindowFlags(flags)
        self.show()
        
    # Tags transform:
    def append_title_id(self):
        idsong = self.edit.selectedText()
        self.edit.del_()
                
        text = self.title_edit.text().rstrip()
        if re.search(r"\(ID:\d+\)$", text):
            return
        
        if text.endswith("(ID: )"):
            return
        
        if text:
            text += " "
        self.title_edit.setText(text + f"(ID: {idsong})")
        
    def move_artist_filename_to_artist(self):
        artist_selection = self.edit.selectedText()
        self.edit.del_()
        
        actual = self.artist_edit.text() 
        
        if actual:
            nuevo = actual + "/" + artist_selection.replace(" - ", '')
        else:
            nuevo = actual + artist_selection.replace(" - ", '')
        
        self.artist_edit.setText(nuevo)        

    def move_title_filename_to_title(self):
        title_selection = self.edit.selectedText()        
        actual = self.title_edit.text() 
        
        if actual:
            nuevo = actual + " " + title_selection.replace(" - ", '')
        else:
            nuevo = actual + title_selection.replace(" - ", '')
        
        self.title_edit.setText(nuevo)

    # newgrounds dialog
    def open_ng_dialog(self):
        dlg = NewgroundsDialog(idsong=self.edit.selectedText() or self.title_edit.selectedText(), parent=self)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        data = dlg.result_data
        if not data:
            return

        ng_id = data.get("ng_id", "").strip()

        # --- TITLE ---
        title = data.get("title")
        if title:
            title = title.rstrip()
            if not re.search(rf"\(ID:\s*{re.escape(ng_id)}\)$", title):
                title += f" (ID: {ng_id})"
            self.title_edit.setText(title)

        # --- ARTIST ---
        artist = data.get("artist")
        if artist:
            self.artist_edit.setText(artist)

        # --- FILENAME / RENAME ---
        filename = data.get("filename")
        if filename:
            filename = filename.strip()

            # Sanitizar para Windows
            filename = sanitize_windows_filename(filename)

            current = self.edit.text().strip()

            # Si ya tiene (η), no mover ni duplicar
            if current.endswith(" (η)"):
                # Solo reemplazamos el texto base, conservando el (η)
                base = current[:-4].rstrip()
                if base:
                    filename = base + " (η)"
                else:
                    filename = filename + " (η)"
            else:
                filename = filename + " (η)"

            self.edit.setText(filename)

    # Single action: apply tags and optionally rename (with permission check)
    def on_rename_clicked(self):
        found_fail = False
        new_name = self.edit.text().strip()
        if not new_name:
            QtWidgets.QMessageBox.warning(self, "Error", "El nombre no puede estar vacío.")
            return
        if any(c in new_name for c in (os.sep, os.altsep) if c):
            QtWidgets.QMessageBox.critical(self, "Error", "El nombre no puede contener separadores de ruta.")
            return
        
        new_path = os.path.join(self.dir_path, new_name + self.ext)
        is_same_path = os.path.abspath(new_path) == os.path.abspath(self.file_path)
        if not is_same_path and os.path.exists(new_path):
            QtWidgets.QMessageBox.critical(self, "Rename failed", "El archivo destino ya existe:\n" + new_path)
            return
        
        # Comprobar si el archivo está en uso (NO esperar)
        if is_file_in_use(self.file_path):
            QtWidgets.QMessageBox.warning(
                self,
                "Archivo en uso",
                "El archivo está siendo usado por otro programa.\n"
                "Ciérralo antes de continuar."
            )
            return

        # --- Comprobar archivo destino ---
        if not is_same_path and os.path.exists(new_path):
            QtWidgets.QMessageBox.critical(
                self,
                "Rename fallido",
                f"Ya existe un archivo con ese nombre:\n{new_path}"
            )
            return

        title = self.title_edit.text().strip()
        artist = self.artist_edit.text().strip()
        album = self.album_edit.text().strip()
        year = self.year_edit.text().strip()
        date = self.date_edit.text().strip()
        track = self.track_edit.text().strip()
        disc = self.disc_edit.text().strip()
        genre = self.get_genre_value()
        comment = self.comment_edit.toPlainText().strip()
        
        # Normalizar saltos de línea (importante para MP3 / MP4)
        comment = comment.replace('\r\n', '\n')        
        
        validated = self.validate_metadata_fields()
        if validated is None:
            return

        year, date, disc = validated
        if self.overwrite_checkbox.isChecked() and genre not in self.genre_choices:
            genre = ""

        if track and not re.fullmatch(r'^\d{1,3}(/\d{2,3})?$', track):
            QtWidgets.QMessageBox.warning(
                self,
                "Track inválido",
                "Formatos válidos:\n"
                "00, 000, 00/00, 00/000, 000/000"
            )
            return

        while True:
            try:
                # Wait until file is unlocked
                wait_until_file_unlocked(self.file_path)

                # Save original timestamps
                st = os.stat(self.file_path)
                orig_ctime = st.st_ctime
                orig_mtime = st.st_mtime
                orig_atime = st.st_atime

                # Check whether we have permission to modify file contents (metadata)
                has_write_perm = can_write_file(self.file_path)

                if not has_write_perm:
                    # Inform user that metadata will not be changed due to permissions; proceed with rename only.
                    QtWidgets.QMessageBox.warning(
                        self,
                        "Permisos insuficientes",
                        "No se detectaron permisos para modificar el archivo. Revise los atributos o si otro proceso usa el archivo"
                    )
                    return
                else:
                    # attempt to write tags (best-effort)
                    try:
                        write_tags(
                            self.file_path,
                            title if title else '',
                            artist if artist else '',
                            comment if comment else '',
                            album if album else '',
                            year if year else '',
                            date if date else '',
                            track if track else '',
                            disc if disc else '',
                            genre if genre else ''
                        )
                    except Exception as e:
                        # if writing tags fails unexpectedly, inform and continue (we will still attempt rename)
                        # tb_str = traceback.format_exc()
                        QtWidgets.QMessageBox.warning(self, "Advertencia al escribir etiquetas", f"No se pudieron aplicar las etiquetas: {e}")
                        return

                final_path = self.file_path

                # Perform rename if name changed
                if not is_same_path:
                    os.rename(self.file_path, new_path)
                    final_path = new_path

                    # Update internal state
                    self.file_path = os.path.abspath(new_path)
                    self.base_name = os.path.basename(self.file_path)
                    self.name, self.ext = os.path.splitext(self.base_name)

                # Restore timestamps as the final filesystem operation so tag writes and
                # optional renames cannot leave a newer modification date behind.
                try:
                    os.utime(final_path, (orig_atime, orig_mtime))
                except Exception:
                    pass
                try:
                    set_creation_and_modification_windows(final_path, orig_ctime, orig_mtime)
                except Exception:
                    pass
                
                break
            except PermissionError as e:
                if es_solo_lectura_windows(self.file_path):
                    QtWidgets.QMessageBox.critical(self, "Error al renombrar el archivo", f"No se pudo completar la operación:\n{e}")
                    break
                wait_until_file_unlocked(self.file_path)
            except Exception as e:
                found_fail = True
                QtWidgets.QMessageBox.critical(self, "Error al renombrar el archivo", f"No se pudo completar la operación:\n{e}")
                break
                
        if not found_fail:
            self.close()

    def load_cover_art(self):
        data = read_cover_art(self.file_path)
        if not data:
            self.cover_label.setPixmap(QtGui.QPixmap())
            self.cover_label.set_has_cover(False)
            return

        pixmap = QtGui.QPixmap()
        pixmap.loadFromData(data)
        if pixmap.isNull():
            self.cover_label.setPixmap(QtGui.QPixmap())
            self.cover_label.set_has_cover(False)
            return

        self.cover_label.set_has_cover(True)
        self.cover_label.setText("")
        self.cover_label.setPixmap(
            pixmap.scaled(
                self.cover_label.width(),
                self.cover_label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )
        )


    def _run_preserving_file_times(self, callback):
        st = os.stat(self.file_path)
        orig_ctime = st.st_ctime
        orig_mtime = st.st_mtime
        orig_atime = st.st_atime

        callback()

        # Keep timestamp restoration last because embedding artwork updates the file.
        try:
            os.utime(self.file_path, (orig_atime, orig_mtime))
        except Exception:
            pass
        try:
            set_creation_and_modification_windows(self.file_path, orig_ctime, orig_mtime)
        except Exception:
            pass


    def replace_cover_from_dialog(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Seleccionar carátula",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)"
        )
        if not path:
            return

        try:
            self._run_preserving_file_times(lambda: write_cover_art(self.file_path, path))
            self.load_cover_art()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"No se pudo guardar la carátula:\n{e}")


    def show_cover_context_menu(self, pos):
        menu = QtWidgets.QMenu(self)
        act_export = menu.addAction("Exportar imagen")
        act_replace = menu.addAction("Remplazar")
        act_copy = menu.addAction("Copiar imagen al portapapeles")
        act_paste = menu.addAction("Pegar imagen del portapapeles")

        action = menu.exec(pos)
        if action == act_export:
            self.export_cover_from_dialog()
        elif action == act_replace:
            self.replace_cover_from_dialog()
        elif action == act_copy:
            self.copy_cover_to_clipboard()
        elif action == act_paste:
            self.paste_cover_from_clipboard()

    def copy_cover_to_clipboard(self):
        data = read_cover_art(self.file_path)
        if not data:
            QtWidgets.QMessageBox.information(self, "Carátula", "No hay carátula para copiar.")
            return

        pixmap = QtGui.QPixmap()
        pixmap.loadFromData(data)
        if pixmap.isNull():
            QtWidgets.QMessageBox.warning(self, "Carátula", "No se pudo leer la imagen.")
            return

        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setPixmap(pixmap)
        clipboard.setImage(pixmap.toImage())

    def paste_cover_from_clipboard(self):
        clipboard = QtWidgets.QApplication.clipboard()
        image = clipboard.image()
        if image.isNull():
            pixmap = clipboard.pixmap()
            if not pixmap.isNull():
                image = pixmap.toImage()

        if image.isNull():
            QtWidgets.QMessageBox.information(
                self,
                "Carátula",
                "No hay una imagen válida en el portapapeles."
            )
            return

        buffer = QBuffer()
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not image.save(buffer, "PNG"):
            QtWidgets.QMessageBox.warning(self, "Carátula", "No se pudo leer la imagen del portapapeles.")
            return

        try:
            data = bytes(buffer.data())
            self._run_preserving_file_times(
                lambda: write_cover_art_data(self.file_path, data, "image/png")
            )
            self.load_cover_art()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"No se pudo pegar la carátula:\n{e}")


    def export_cover_from_dialog(self):
        data = read_cover_art(self.file_path)
        if not data:
            QtWidgets.QMessageBox.information(self, "Carátula", "No hay carátula para exportar.")
            return

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Exportar carátula",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.webp);;All Files (*)"
        )
        if not path:
            return

        try:
            export_cover_art(self.file_path, path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"No se pudo exportar la carátula:\n{e}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python script.py <file>")
        return

    app = QtWidgets.QApplication(sys.argv)
    try:
        app.setWindowIcon(QtGui.QIcon(ICON_WIN))
    except Exception:
        pass

    dlg = RenameDialog(sys.argv[1])
    dlg.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
