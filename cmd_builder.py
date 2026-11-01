import sys
import os
import ctypes
from pathlib import Path
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QLineEdit, QCheckBox, QComboBox, QPushButton,
    QTextEdit, QGroupBox, QFormLayout, QFileDialog, QMessageBox
)

APP_DIR = Path(__file__).resolve().parent.as_posix()
ICON_WIN = f"{APP_DIR}/assets/command_line.ico"
myappid = 'etudetools.files_mgr.rename_dialog.1.0'
try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
except Exception:
    pass

class CommandBuilderApp(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Command Builder — yt-dlp & gallery-dl")
        self.resize(850, 680)
        
        # Aplicar un estilo oscuro personalizado
        self.apply_dark_theme()

        # UI Principal
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # Tabs para elegir la herramienta
        self.tabs = QTabWidget()
        self.tab_ytdlp = QWidget()
        self.tab_gallerydl = QWidget()

        self.tabs.addTab(self.tab_ytdlp, "yt-dlp")
        self.tabs.addTab(self.tab_gallerydl, "gallery-dl")
        
        self.setup_ytdlp_tab()
        self.setup_gallerydl_tab()
        
        main_layout.addWidget(self.tabs)

        # Caja para el comando resultante
        output_box = QGroupBox("Comando Generado")
        output_layout = QVBoxLayout(output_box)

        self.cmd_output = QTextEdit()
        self.cmd_output.setReadOnly(True)
        self.cmd_output.setFixedHeight(80)
        self.cmd_output.setFont(QFont("Consolas", 10))
        output_layout.addWidget(self.cmd_output)

        # Botones de acción
        btn_layout = QHBoxLayout()
        self.btn_copy = QPushButton("Copiar al Portapapeles")
        self.btn_copy.setFixedHeight(35)
        self.btn_copy.clicked.connect(self.copy_to_clipboard)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_copy)
        output_layout.addLayout(btn_layout)

        main_layout.addWidget(output_box)

        # Conectar actualizaciones automáticas
        self.tabs.currentChanged.connect(self.generate_command)
        
        # Generar primer comando
        self.generate_command()

    def apply_dark_theme(self):
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.Base, QColor(20, 20, 20))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(30, 30, 30))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.Button, QColor(45, 45, 45))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(100, 40, 60))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        self.setPalette(palette)

    # --------------------------------------------------
    # TAB: yt-dlp
    # --------------------------------------------------
    def setup_ytdlp_tab(self):
        layout = QVBoxLayout(self.tab_ytdlp)
        form = QFormLayout()
        form.setSpacing(10)

        # URL Input
        self.yt_url = QLineEdit()
        self.yt_url.setPlaceholderText("https://www.youtube.com/watch?v=...")
        self.yt_url.textChanged.connect(self.generate_command)
        form.addRow("URL de entrada:", self.yt_url)

        # Formato / Audio
        self.yt_format = QComboBox()
        self.yt_format.addItems([
            "Mejor calidad disponible (default)",
            "Solo Audio (MP3)",
            "Solo Audio (FLAC)",
            "Solo Audio (Opus)",
            "Video 1080p (MP4/MKV)",
            "Video 720p (MP4)",
            "Personalizado / Especificar -f"
        ])
        self.yt_format.currentIndexChanged.connect(self.generate_command)
        form.addRow("Formato de descarga:", self.yt_format)

        self.yt_custom_format = QLineEdit()
        self.yt_custom_format.setPlaceholderText("ej. bestvideo[height<=1080]+bestaudio/best")
        self.yt_custom_format.setEnabled(False)
        self.yt_custom_format.textChanged.connect(self.generate_command)
        self.yt_format.currentIndexChanged.connect(
            lambda i: self.yt_custom_format.setEnabled(i == 6)
        )
        form.addRow("Fórmula de formato (-f):", self.yt_custom_format)

        # Carpeta de salida por defecto (Downloads)
        default_downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        dir_layout = QHBoxLayout()
        self.yt_dir = QLineEdit(default_downloads)
        self.yt_dir.textChanged.connect(self.generate_command)
        btn_browse_yt = QPushButton("Examinar...")
        btn_browse_yt.clicked.connect(lambda: self.browse_folder(self.yt_dir))
        dir_layout.addWidget(self.yt_dir)
        dir_layout.addWidget(btn_browse_yt)
        form.addRow("Carpeta de salida (-P):", dir_layout)

        # Plantilla del nombre de archivo (-o)
        self.yt_output_template = QLineEdit("%(title)s [%(id)s].%(ext)s")
        self.yt_output_template.textChanged.connect(self.generate_command)
        form.addRow("Plantilla de salida (-o):", self.yt_output_template)

        # Checkbox para numeración de playlist
        self.yt_playlist_num = QCheckBox("Añadir numeración de lista de reproducción (%(playlist_index)s)")
        self.yt_playlist_num.setChecked(True)  # Activado por defecto para mayor comodidad
        self.yt_playlist_num.stateChanged.connect(self.generate_command)
        form.addRow("Numeración Playlist:", self.yt_playlist_num)

        # Opción Subtítulos
        self.yt_subtitles = QCheckBox("Descargar subtítulos e incrustarlos (--embed-subs)")
        self.yt_subtitles.stateChanged.connect(self.generate_command)
        form.addRow("Subtítulos:", self.yt_subtitles)

        # Metadata y Miniaturas
        self.yt_metadata = QCheckBox("Incrustar metadatos y miniatura (--embed-metadata --embed-thumbnail)")
        self.yt_metadata.stateChanged.connect(self.generate_command)
        form.addRow("Metadatos:", self.yt_metadata)

        # Archivo de cookies
        cookie_layout = QHBoxLayout()
        self.yt_cookies = QLineEdit()
        self.yt_cookies.setPlaceholderText("Ruta a cookies.txt (opcional)")
        self.yt_cookies.textChanged.connect(self.generate_command)
        btn_browse_cookie = QPushButton("Buscar...")
        btn_browse_cookie.clicked.connect(lambda: self.browse_file(self.yt_cookies, "Text Files (*.txt)"))
        cookie_layout.addWidget(self.yt_cookies)
        cookie_layout.addWidget(btn_browse_cookie)
        form.addRow("Cookies (--cookies):", cookie_layout)

        # Argumentos Extra
        self.yt_extra = QLineEdit()
        self.yt_extra.setPlaceholderText("ej. --no-playlist --rate-limit 1.5M")
        self.yt_extra.textChanged.connect(self.generate_command)
        form.addRow("Argumentos extra:", self.yt_extra)

        layout.addLayout(form)
        layout.addStretch()

    # --------------------------------------------------
    # TAB: gallery-dl
    # --------------------------------------------------
    def setup_gallerydl_tab(self):
        layout = QVBoxLayout(self.tab_gallerydl)
        form = QFormLayout()
        form.setSpacing(10)

        # URL Input
        self.gdl_url = QLineEdit()
        self.gdl_url.setPlaceholderText("https://site.com/gallery/...")
        self.gdl_url.textChanged.connect(self.generate_command)
        form.addRow("URL de Galería / Perfil:", self.gdl_url)

        # Carpeta de salida por defecto (Downloads)
        default_downloads = os.path.join(os.path.expanduser("~"), "Downloads")
        dir_layout = QHBoxLayout()
        self.gdl_dir = QLineEdit(default_downloads)
        self.gdl_dir.textChanged.connect(self.generate_command)
        btn_browse_gdl = QPushButton("Examinar...")
        btn_browse_gdl.clicked.connect(lambda: self.browse_folder(self.gdl_dir))
        dir_layout.addWidget(self.gdl_dir)
        dir_layout.addWidget(btn_browse_gdl)
        form.addRow("Carpeta de destino (-d):", dir_layout)

        # Límite de imágenes
        self.gdl_range = QLineEdit()
        self.gdl_range.setPlaceholderText("ej. 1-20 o 1,3,5 (dejar vacío para todo)")
        self.gdl_range.textChanged.connect(self.generate_command)
        form.addRow("Rango / Cantidad (--range):", self.gdl_range)

        # Autenticación / Login
        auth_layout = QHBoxLayout()
        self.gdl_user = QLineEdit()
        self.gdl_user.setPlaceholderText("Usuario")
        self.gdl_user.textChanged.connect(self.generate_command)
        self.gdl_pass = QLineEdit()
        self.gdl_pass.setPlaceholderText("Contraseña")
        self.gdl_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.gdl_pass.textChanged.connect(self.generate_command)
        auth_layout.addWidget(self.gdl_user)
        auth_layout.addWidget(self.gdl_pass)
        form.addRow("Credenciales (-u / -p):", auth_layout)

        # OAuth / Cookies / Browser
        self.gdl_browser = QComboBox()
        self.gdl_browser.addItems(["Ninguno", "chrome", "firefox", "edge", "opera", "brave", "vivaldi"])
        self.gdl_browser.currentIndexChanged.connect(self.generate_command)
        form.addRow("Extraer cookies del navegador (--cookies-from-browser):", self.gdl_browser)

        # Opciones varias
        self.gdl_write_metadata = QCheckBox("Guardar metadatos en JSON separado (--write-metadata)")
        self.gdl_write_metadata.stateChanged.connect(self.generate_command)
        form.addRow("Metadatos:", self.gdl_write_metadata)

        self.gdl_write_tags = QCheckBox("Guardar tags/descripciones en archivo txt (--write-tags)")
        self.gdl_write_tags.stateChanged.connect(self.generate_command)
        form.addRow("Tags:", self.gdl_write_tags)

        self.gdl_unzip = QCheckBox("Extraer archivos ZIP descargados (--unzip)")
        self.gdl_unzip.stateChanged.connect(self.generate_command)
        form.addRow("Archivos:", self.gdl_unzip)

        # Argumentos Extra
        self.gdl_extra = QLineEdit()
        self.gdl_extra.setPlaceholderText("ej. --filter \"rating == 'g'\" --retries 5")
        self.gdl_extra.textChanged.connect(self.generate_command)
        form.addRow("Argumentos extra:", self.gdl_extra)

        layout.addLayout(form)
        layout.addStretch()

    # --------------------------------------------------
    # LÓGICA DE GENERACIÓN DE COMANDOS
    # --------------------------------------------------
    def generate_command(self):
        active_tab_index = self.tabs.currentIndex()

        if active_tab_index == 0:
            # === GENERAR YT-DLP ===
            cmd = ["yt-dlp"]
            
            # Formato
            fmt_idx = self.yt_format.currentIndex()
            if fmt_idx == 1:
                cmd.extend(["-x", "--audio-format", "mp3"])
            elif fmt_idx == 2:
                cmd.extend(["-x", "--audio-format", "flac"])
            elif fmt_idx == 3:
                cmd.extend(["-x", "--audio-format", "opus"])
            elif fmt_idx == 4:
                cmd.extend(["-f", "\"bestvideo[height<=1080]+bestaudio/best\""])
            elif fmt_idx == 5:
                cmd.extend(["-f", "\"bestvideo[height<=720]+bestaudio/best\""])
            elif fmt_idx == 6 and self.yt_custom_format.text().strip():
                cmd.extend(["-f", f"\"{self.yt_custom_format.text().strip()}\""])

            # Subtítulos & Metadata
            if self.yt_subtitles.isChecked():
                cmd.extend(["--embed-subs", "--sub-langs", "all"])
            if self.yt_metadata.isChecked():
                cmd.extend(["--embed-metadata", "--embed-thumbnail"])

            # Rutas y salida
            if self.yt_dir.text().strip():
                cmd.extend(["-P", f"\"{self.yt_dir.text().strip()}\""])
            
            # Plantilla de salida con opción de playlist index
            template_text = self.yt_output_template.text().strip()
            if template_text:
                if self.yt_playlist_num.isChecked() and "%(playlist_index)s" not in template_text:
                    template_text = f"%(playlist_index)s. {template_text}"
                cmd.extend(["-o", f"\"{template_text}\""])

            # Cookies
            if self.yt_cookies.text().strip():
                cmd.extend(["--cookies", f"\"{self.yt_cookies.text().strip()}\""])

            # Argumentos extra
            if self.yt_extra.text().strip():
                cmd.append(self.yt_extra.text().strip())

            # URL al final
            url = self.yt_url.text().strip()
            cmd.append(f"\"{url}\"" if url else "<URL_AQUÍ>")

            self.cmd_output.setPlainText(" ".join(cmd))

        else:
            # === GENERAR GALLERY-DL ===
            cmd = ["gallery-dl"]

            # Destino
            if self.gdl_dir.text().strip():
                cmd.extend(["-d", f"\"{self.gdl_dir.text().strip()}\""])

            # Rango
            if self.gdl_range.text().strip():
                cmd.extend(["--range", f"\"{self.gdl_range.text().strip()}\""])

            # Credenciales
            if self.gdl_user.text().strip():
                cmd.extend(["-u", f"\"{self.gdl_user.text().strip()}\""])
            if self.gdl_pass.text().strip():
                cmd.extend(["-p", f"\"{self.gdl_pass.text().strip()}\""])

            # Cookies de Navegador
            if self.gdl_browser.currentIndex() > 0:
                cmd.extend(["--cookies-from-browser", self.gdl_browser.currentText()])

            # Flags varias
            if self.gdl_write_metadata.isChecked():
                cmd.append("--write-metadata")
            if self.gdl_write_tags.isChecked():
                cmd.append("--write-tags")
            if self.gdl_unzip.isChecked():
                cmd.append("--unzip")

            # Argumentos extra
            if self.gdl_extra.text().strip():
                cmd.append(self.gdl_extra.text().strip())

            # URL al final
            url = self.gdl_url.text().strip()
            cmd.append(f"\"{url}\"" if url else "<URL_AQUÍ>")

            self.cmd_output.setPlainText(" ".join(cmd))

    # --------------------------------------------------
    # MÉTODOS AUXILIARES
    # --------------------------------------------------
    def browse_folder(self, target_line_edit):
        folder = QFileDialog.getExistingDirectory(self, "Seleccionar Carpeta Destino")
        if folder:
            target_line_edit.setText(folder)

    def browse_file(self, target_line_edit, file_filter="All Files (*)"):
        file_path, _ = QFileDialog.getOpenFileName(self, "Seleccionar Archivo", "", file_filter)
        if file_path:
            target_line_edit.setText(file_path)

    def copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.cmd_output.toPlainText())
        self.btn_copy.setText("✓ ¡Copiado!")
        QTimer.singleShot(1500, lambda: self.btn_copy.setText("Copiar al Portapapeles"))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(ICON_WIN))
    window = CommandBuilderApp()
    window.show()
    sys.exit(app.exec())