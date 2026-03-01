"""
Localization module - manages application strings in multiple languages.
Módulo de Localización: gestiona las cadenas de la aplicación en varios idiomas.
"""

import json
import logging
from typing import Dict
from config import LANG_PATH

STRINGS = {
    "es": {
        "btn_keep": "Conservar",
        "btn_delete": "Eliminar",
        "btn_undo": "Deshacer",
        "btn_apply": "Aplicar",
        "btn_apply_custom": "Aplicar Personalizado",
        "btn_secure": "Seguridad",
        "btn_open": "Abrir",
        "lbl_type": "Tipo",
        "lbl_characters": "Personajes",
        "lbl_queue": "Cola de descargas",
        "lbl_years": "Años",
        "lbl_subfolders": "Subcarpetas",
        "lbl_new_name": "Nuevo nombre (opcional):",
        "lbl_custom_dest": "Destino personalizado:",
        "msg_no_file": "Esperando archivos...",
        "msg_exit_title": "Confirmar salida",
        "msg_exit_confirm": "¿Estás seguro de que deseas detener el servicio?",
        "tray_exit": "Salir",
        "tray_order_pending": "Ordenar pendientes",
        "tray_run_pendings": "Ejecutar pendientes",
        "tray_undo": "Deshacer último movimiento",
        "tray_center": "Traer y centrar",
        "tray_show": "Mostrar",
        "tray_hide": "Ocultar",
        "tray_rescan": "Volver a escanear",
        "tray_logs": "Ver Logs",
        "tray_restart": "Reiniciar servicio",
        "lang_name": "Español",
        "lang_toggle": "EN",
        "btn_history": "Deshacer",
        "btn_header_delete": "Eliminar",
        "btn_hide": "Ocultar",
        "msg_pending_files": "Hay archivos pendientes",
        "btn_show_again": "Mostrar de nuevo",
        "type_1": "1 Mantener en descargas",
        "type_2": "2 Personajes y Screenshots",
        "type_3": "3 Episodios",
        "type_4": "4 Musica",
        "type_5": "5 Academico",
        "type_6": "6 Familiar y Tramites",
        "type_7": "7 Documentacion lineal",
        "type_8": "8 Overworld",
        "menu_create_folder": "Crear nueva carpeta aqui",
        "menu_rename_folder": "Renombrar esta carpeta",
        "menu_delete_folder": "Eliminar esta carpeta vacía",
        "dlg_create_title": "Nueva carpeta",
        "dlg_create_label": "Nombre de la carpeta:",
        "dlg_rename_title": "Renombrar carpeta",
        "dlg_rename_label": "Nuevo nombre:",
        "dlg_delete_title": "Eliminar carpeta",
        "dlg_delete_confirm": "¿Estás seguro de que deseas eliminar esta carpeta?",
    },
    "en": {
        "btn_keep": "Keep",
        "btn_delete": "Delete",
        "btn_undo": "Undo",
        "btn_apply": "Apply",
        "btn_apply_custom": "Apply Custom",
        "btn_secure": "Secure",
        "btn_open": "Open",
        "lbl_type": "Type",
        "lbl_characters": "Characters",
        "lbl_queue": "Download Queue",
        "lbl_years": "Years",
        "lbl_subfolders": "Subfolders",
        "lbl_new_name": "New name (optional):",
        "lbl_custom_dest": "Custom destination:",
        "msg_no_file": "Waiting for files...",
        "msg_exit_title": "Confirm Exit",
        "msg_exit_confirm": "Are you sure you want to stop the service?",
        "tray_exit": "Exit",
        "tray_order_pending": "Order pending",
        "tray_run_pendings": "Run pending",
        "tray_undo": "Undo last move",
        "tray_center": "Bring and center",
        "tray_show": "Show",
        "tray_hide": "Hide",
        "tray_rescan": "Rescan",
        "tray_logs": "View Logs",
        "tray_restart": "Restart Service",
        "lang_name": "English",
        "lang_toggle": "ES",
        "btn_history": "Undo",
        "btn_header_delete": "Delete",
        "btn_hide": "Hide",
        "msg_pending_files": "There are pending files",
        "btn_show_again": "Show Again",
        "type_1": "1 Keep in downloads",
        "type_2": "2 Characters and Screenshots",
        "type_3": "3 Episodes",
        "type_4": "4 Music",
        "type_5": "5 Academic",
        "type_6": "6 Family and Procedures",
        "type_7": "7 Linear Documentation",
        "type_8": "8 Overworld",
        "menu_create_folder": "Create new folder here",
        "menu_rename_folder": "Rename this folder",
        "menu_delete_folder": "Delete this empty folder",
        "dlg_create_title": "New folder",
        "dlg_create_label": "Folder name:",
        "dlg_rename_title": "Rename folder",
        "dlg_rename_label": "New name:",
        "dlg_delete_title": "Delete folder",
        "dlg_delete_confirm": "Are you sure you want to delete this folder?",
    }
}

class LocalizationManager:
    """
    Manages the current language and provides translated strings.
    Gestiona el idioma actual y proporciona cadenas traducidas.
    """
    def __init__(self):
        self.lang = self._load_lang()

    def _load_lang(self) -> str:
        if LANG_PATH.exists():
            try:
                with open(LANG_PATH, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    return config.get("lang", "es")
            except Exception:
                logging.exception("Error loading language config")
        return "es"

    def _save_lang(self):
        try:
            with open(LANG_PATH, 'w', encoding='utf-8') as f:
                json.dump({"lang": self.lang}, f, indent=4)
        except Exception:
            logging.exception("Error saving language config")

    def toggle_lang(self):
        self.lang = "en" if self.lang == "es" else "es"
        self._save_lang()

    def get(self, key: str) -> str:
        return STRINGS.get(self.lang, STRINGS["es"]).get(key, key)

    def current_lang(self) -> str:
        return self.lang
