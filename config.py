"""
Configuration module - App constants and path definitions.
Módulo de Configuración: constantes de la aplicación y definiciones de rutas.

Contains global settings, path definitions for internal and cloud storage,
and application metadata.
Contiene configuraciones globales, definiciones de rutas para almacenamiento
interno y en la nube, y metadatos de la aplicación.
"""

import os
from pathlib import Path
from datetime import datetime

# App Metadata
APP_NAME = "CatchEtude"
MYAPPID = 'EtudeProduts.CatchEtude.CatchEtudeWatcher.v1.0'

# Icons and Paths
ICON_PATH = r"C:\Users\miche\OneDrive\CatchEtude\catchetude-icon.png"
USER_HOME = Path.home()
DOWNLOADS = USER_HOME / "Downloads"
DOCUMENTS = USER_HOME / "Documents"
CONFLICTS = DOCUMENTS / "_conflicts"
APPDATA_DIR = Path(os.getenv("APPDATA", USER_HOME)) / APP_NAME
CONFIG_PATH = APPDATA_DIR / "config.json"
HISTORY_PATH = APPDATA_DIR / "history.json"
CRASH_REPORT_PATH = APPDATA_DIR / "last_crash.txt"
LANG_PATH = APPDATA_DIR / "lang.json"
LOG_FILENAME = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log"
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_PATH = LOG_DIR / LOG_FILENAME
CACHE_DIR = APPDATA_DIR / ".cache"

# Internal and Cloud Storage
BASE_INTERNAL = Path(r"E:\_Internal")
ONEDRIVE_DOCS = USER_HOME / "OneDrive" / "Documentos"
ONEDRIVE_DOCTOS_FAMILIA = USER_HOME / "OneDrive" / "Doctos Familia"

# Folder Name Keywords
CHAR_PANEL_ALWAYS = False # Set to True to keep character panel always visible
BLUR_LEVEL = 15
HDD_SPINUP_MS = 1500
IMAGES_FOLDER = "etude.dorothy.images"
MUSIC_FOLDER = "music.ahead"
OVERWORLD_FOLDER = "resources.local.overworld"
ACROBAT_FOLDER = "resources.local.acrobat"

# Filters and Date
EXCLUDE_EXT = {'.crdownload', '.part', '.tmp', '.temp', '.catchtmp', '.ini'}
CURRENT_YEAR = datetime.now().year
YEARS = list(range(2004, CURRENT_YEAR + 1))

# Initialize Directories
APPDATA_DIR.mkdir(parents=True, exist_ok=True)
CONFLICTS.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Windows Error Codes
ERROR_ALREADY_EXISTS = 183

# DWM (Desktop Window Manager) Constants
DWMWA_HAS_ICONIC_BITMAP = 10
DWMWA_FORCE_ICONIC_REPRESENTATION = 7
DWMWA_DISALLOW_PEEK = 11
