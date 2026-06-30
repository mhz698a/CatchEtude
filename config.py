"""
Configuration module - App constants and path definitions.
Módulo de Configuración: constantes de la aplicación y definiciones de rutas.

Contains global settings, path definitions for internal and cloud storage,
and application metadata.
Contiene configuraciones globales, definiciones de rutas para almacenamiento
interno y en la nube, y metadatos de la aplicación.
"""

import os
import sys
import logging
from pathlib import Path
from datetime import datetime

# App Metadata
APP_NAME = "CatchEtude"
MYAPPID = 'EtudeProduts.CatchEtude.CatchEtudeWatcher.v1.0'

APP_DIR = Path(__file__).resolve().parent.as_posix()
USER_HOME = Path.home()

ICON_PATH = f"{APP_DIR}/assets/catchetude-icon.png"

# Default values for configurable settings
DEFAULT_SETTINGS = {
    "METADATA_EDIT_SCRIPT_PATH": (USER_HOME / "OneDrive" / "foobar2000" / "profile" / "ActivityBar" / "rename_dialog.py").as_posix(),
    "CONFLICTS": (USER_HOME / "Documents" / "_conflicts").as_posix(),
    "BASE_INTERNAL": r"E:\_Internal",
    "ONEDRIVE_DOCS": (USER_HOME / "OneDrive" / "Documentos").as_posix(),
    "ONEDRIVE_DOCTOS_FAMILIA": (USER_HOME / "OneDrive" / "Doctos Familia").as_posix(),
    "BLUR_LEVEL": 15,
    "IMAGES_FOLDER": "album",
    "MUSIC_FOLDER": "music",
    "OVERWORLD_FOLDER": "overworld",
    "ACROBAT_FOLDER": "resources.local.acrobat",
}

DOWNLOADS = USER_HOME / "Downloads"
DOCUMENTS = USER_HOME / "Documents"
APPDATA_DIR = Path(os.getenv("APPDATA", USER_HOME)) / APP_NAME
# Ensure APPDATA_DIR exists early
APPDATA_DIR.mkdir(parents=True, exist_ok=True)

SETTINGS_PATH = APPDATA_DIR / "settings.toml"
CONFIG_PATH = APPDATA_DIR / "config.json"
HISTORY_PATH = APPDATA_DIR / "history.json"
CRASH_REPORT_PATH = APPDATA_DIR / "last_crash.txt"
LANG_PATH = APPDATA_DIR / "lang.json"
LOG_FILENAME = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log"
LOG_DIR = APPDATA_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_PATH = LOG_DIR / LOG_FILENAME
CACHE_DIR = APPDATA_DIR / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

def save_settings(settings):
    """Saves settings to TOML file."""
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            for key, value in settings.items():
                if isinstance(value, str):
                    # Escape backslashes for Windows paths
                    escaped_value = value.replace("\\", "\\\\")
                    f.write(f'{key} = "{escaped_value}"\n')
                else:
                    f.write(f'{key} = {value}\n')
    except Exception as e:
        logging.error(f"Error saving settings: {e}")

def load_settings():
    """Loads settings from TOML file or creates defaults."""
    if not SETTINGS_PATH.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS

    try:
        import tomllib
        with open(SETTINGS_PATH, "rb") as f:
            return tomllib.load(f)
    except Exception as e:
        logging.error(f"Error loading settings: {e}")
        return DEFAULT_SETTINGS

def apply_settings():
    """Applies settings to the current module and propagates changes."""
    settings = load_settings()
    module = sys.modules[__name__]

    changed_keys = []
    for key, value in settings.items():
        # Handle Path conversion for specific keys
        if key in ["METADATA_EDIT_SCRIPT_PATH", "CONFLICTS", "BASE_INTERNAL", "ONEDRIVE_DOCS", "ONEDRIVE_DOCTOS_FAMILIA"]:
            value = Path(value)

        old_value = getattr(module, key, None)
        if old_value != value:
            setattr(module, key, value)
            changed_keys.append(key)

    # If CONFLICTS changed, ensure it exists
    if "CONFLICTS" in changed_keys:
        module.CONFLICTS.mkdir(parents=True, exist_ok=True)

    # Propagate changes to other modules
    if changed_keys:
        for mod_name, mod in sys.modules.items():
            if mod_name == __name__ or mod is None:
                continue
            for key in changed_keys:
                if hasattr(mod, key):
                    try:
                        setattr(mod, key, getattr(module, key))
                    except Exception:
                        pass

# Initial load and application of settings
_current_settings = load_settings()

METADATA_EDIT_SCRIPT_PATH = Path(_current_settings.get("METADATA_EDIT_SCRIPT_PATH", DEFAULT_SETTINGS["METADATA_EDIT_SCRIPT_PATH"]))
CONFLICTS = Path(_current_settings.get("CONFLICTS", DEFAULT_SETTINGS["CONFLICTS"]))
BASE_INTERNAL = Path(_current_settings.get("BASE_INTERNAL", DEFAULT_SETTINGS["BASE_INTERNAL"]))
ONEDRIVE_DOCS = Path(_current_settings.get("ONEDRIVE_DOCS", DEFAULT_SETTINGS["ONEDRIVE_DOCS"]))
ONEDRIVE_DOCTOS_FAMILIA = Path(_current_settings.get("ONEDRIVE_DOCTOS_FAMILIA", DEFAULT_SETTINGS["ONEDRIVE_DOCTOS_FAMILIA"]))
BLUR_LEVEL = _current_settings.get("BLUR_LEVEL", DEFAULT_SETTINGS["BLUR_LEVEL"])
IMAGES_FOLDER = _current_settings.get("IMAGES_FOLDER", DEFAULT_SETTINGS["IMAGES_FOLDER"])
MUSIC_FOLDER = _current_settings.get("MUSIC_FOLDER", DEFAULT_SETTINGS["MUSIC_FOLDER"])
OVERWORLD_FOLDER = _current_settings.get("OVERWORLD_FOLDER", DEFAULT_SETTINGS["OVERWORLD_FOLDER"])
ACROBAT_FOLDER = _current_settings.get("ACROBAT_FOLDER", DEFAULT_SETTINGS["ACROBAT_FOLDER"])

# Non-configurable constants
EXCLUDE_EXT = {'.crdownload', '.part', '.tmp', '.temp', '.catchtmp', '.ini'}
METADATA_EDIT_EXTS = {".mp3", ".mp4", ".m4a", ".m4v"}
CURRENT_YEAR = datetime.now().year
YEARS = list(range(2004, CURRENT_YEAR + 1))
NONCANON_YEARS = [1999, 2000, 2001, 2002, 2003]

# Windows Error Codes
ERROR_ALREADY_EXISTS = 183

# DWM (Desktop Window Manager) Constants
DWMWA_HAS_ICONIC_BITMAP = 10
DWMWA_FORCE_ICONIC_REPRESENTATION = 7
DWMWA_DISALLOW_PEEK = 11

# Ensure CONFLICTS exists
CONFLICTS.mkdir(parents=True, exist_ok=True)
