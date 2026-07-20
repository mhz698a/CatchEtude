import logging
import os
from pathlib import Path
from datetime import datetime
import sys
import tomllib

# App Metadata
APP_NAME = "CatchEtude"
MYAPPID = 'EtudeProduts.CatchEtude.CatchEtudeWatcher.v1.0'

APP_DIR = Path(__file__).resolve().parent.as_posix()
USER_HOME = Path.home()
ICON_PATH = f"{APP_DIR}/assets/catchetude-icon.png"

APPDATA_DIR = Path(os.getenv("APPDATA", USER_HOME)) / APP_NAME
APPDATA_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOADS = USER_HOME / "Downloads"
DOCUMENTS = USER_HOME / "Documents"
CONFIG_PATH = APPDATA_DIR / "config.json"
HISTORY_PATH = APPDATA_DIR / "history.json"
SETTINGS_PATH = APPDATA_DIR / "settings.toml"
CRASH_REPORT_PATH = APPDATA_DIR / "last_crash.txt"

# Logs Constrains
LOG_FILENAME = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log"
LOG_DIR = APPDATA_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_PATH = LOG_DIR / LOG_FILENAME
LANG_PATH = APPDATA_DIR / "lang.json"

# Cache constrains
CACHE_DIR = APPDATA_DIR / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Filters and Date
EXCLUDE_EXT = {'.crdownload', '.part', '.tmp', '.temp', '.catchtmp', '.ini'}
METADATA_EDIT_EXTS = {".mp3", ".mp4", ".m4a", ".m4v"}
CURRENT_YEAR = datetime.now().year
YEARS = list(range(2004, CURRENT_YEAR + 1))
NONCANON_YEARS = [1999, 2000, 2001, 2002, 2003]

# Windows Error Codes Constants
ERROR_ALREADY_EXISTS = 183

# DWM (Desktop Window Manager) Constants
DWMWA_HAS_ICONIC_BITMAP = 10
DWMWA_FORCE_ICONIC_REPRESENTATION = 7
DWMWA_DISALLOW_PEEK = 11

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
    "FORCE_GC": True,
    "TIMER_GC": 500,
}

# Declarar variables iniciales con sus valores por defecto
METADATA_EDIT_SCRIPT_PATH = Path(DEFAULT_SETTINGS["METADATA_EDIT_SCRIPT_PATH"])
CONFLICTS = Path(DEFAULT_SETTINGS["CONFLICTS"])
BASE_INTERNAL = Path(DEFAULT_SETTINGS["BASE_INTERNAL"])
ONEDRIVE_DOCS = Path(DEFAULT_SETTINGS["ONEDRIVE_DOCS"])
ONEDRIVE_DOCTOS_FAMILIA = Path(DEFAULT_SETTINGS["ONEDRIVE_DOCTOS_FAMILIA"])
BLUR_LEVEL = DEFAULT_SETTINGS["BLUR_LEVEL"]
IMAGES_FOLDER = DEFAULT_SETTINGS["IMAGES_FOLDER"]
MUSIC_FOLDER = DEFAULT_SETTINGS["MUSIC_FOLDER"]
OVERWORLD_FOLDER = DEFAULT_SETTINGS["OVERWORLD_FOLDER"]
ACROBAT_FOLDER = DEFAULT_SETTINGS["ACROBAT_FOLDER"]
FORCE_GC = DEFAULT_SETTINGS["FORCE_GC"]
TIMER_GC = DEFAULT_SETTINGS["TIMER_GC"]


# Functions
def save_settings(settings):
    """Saves settings to TOML file using standard escaping."""
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            for key, value in settings.items():
                if isinstance(value, str):
                    # Usamos comillas simples triples para rutas de Windows (evita conflictos de barras)
                    f.write(f"{key} = '''{value}'''\n")
                else:
                    f.write(f'{key} = {value}\n')
    except Exception as e:
        logging.error(f"Error saving settings: {e}")

def load_settings():
    """Loads settings from TOML file using standard tomllib or creates defaults."""
    if not SETTINGS_PATH.exists():
        save_settings(DEFAULT_SETTINGS)
        return DEFAULT_SETTINGS

    try:
        # 👇 LECTURA LIMPIA: tomllib lee el archivo y lo convierte a un diccionario de forma segura
        with open(SETTINGS_PATH, "rb") as f:
            settings = tomllib.load(f)

        # Combinar con los valores por defecto por si agregas configuraciones en el futuro
        full_settings = DEFAULT_SETTINGS.copy()
        full_settings.update(settings)
        return full_settings

    except Exception as e:
        logging.error(f"Error loading settings: {e}")
        return DEFAULT_SETTINGS

def apply_settings():
    """Applies settings to the current module and propagates changes."""
    settings = load_settings()
    module = sys.modules[__name__]

    changed_keys = []
    for key, value in settings.items():
        # Convertir a Path solo las llaves que corresponden a rutas de archivos
        if key in ["METADATA_EDIT_SCRIPT_PATH", "CONFLICTS", "BASE_INTERNAL", "ONEDRIVE_DOCS", "ONEDRIVE_DOCTOS_FAMILIA"]:
            value = Path(value)

        old_value = getattr(module, key, None)
        if old_value != value:
            setattr(module, key, value)
            changed_keys.append(key)

    # Garantizar que la carpeta de conflictos exista
    if "CONFLICTS" in changed_keys or not CONFLICTS.exists():
        module.CONFLICTS.mkdir(parents=True, exist_ok=True)

    # Propagar cambios en caliente a otros módulos activos
    if changed_keys:
        for mod_name, mod in sys.modules.items():
            if mod_name == __name__ or mod is None:
                continue
            for key in changed_keys:
                if hasattr(mod, key):
                    try:
                        setattr(mod, key, getattr(module, key))
                    except Exception as e:
                        logging.error(f"Error to propagate to other modules: {e}")

apply_settings()
