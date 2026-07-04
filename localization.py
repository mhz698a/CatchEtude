"""
Localization module - manages application strings in multiple languages.
Módulo de Localización: gestiona las cadenas de la aplicación en varios idiomas.
"""

import json
import logging
import config
from pathlib import Path
from typing import Dict

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
        "tray_open_last": "Abrir la última carpeta elegida",
        "tray_undo": "Deshacer último movimiento",
        "tray_center": "Traer y centrar",
        "tray_show": "Mostrar",
        "tray_hide": "Ocultar",
        "tray_rescan": "Volver a escanear",
        "tray_logs": "Ver Logs",
        "tray_settings": "Ajustes",
        "tray_restart": "Reiniciar servicio",
        "tray_exit": "Cerrar CatchEtude",
        "lang_name": "Español",
        "lang_toggle": "EN",
        "btn_history": "Deshacer",
        "btn_header_delete": "Eliminar",
        "btn_hide": "Ocultar",
        "msg_pending_files": "Hay archivos pendientes",
        "btn_show_again": "Mostrar de nuevo",
        "type_2": "Personajes",
        "type_3": "Episodios",
        "type_4": "Musica",
        "type_5": "Academico",
        "type_6": "Tramites",
        "type_7": "Documentacion",
        "type_8": "Overworld",
        "menu_open_folder": "Abrir carpeta",
        "menu_move_all_in_folder": "Mover todo en esta carpeta",
        "menu_create_folder": "Crear nueva carpeta aqui",
        "menu_rename_folder": "Renombrar esta carpeta",
        "menu_delete_folder": "Eliminar esta carpeta vacía",
        "menu_hidden_years": "Seleccionar años ocultos",
        "dlg_create_title": "Nueva carpeta",
        "dlg_create_label": "Nombre de la carpeta:",
        "dlg_rename_title": "Renombrar carpeta",
        "dlg_rename_label": "Nuevo nombre:",
        "dlg_delete_title": "Eliminar carpeta",
        "dlg_delete_confirm": "¿Estás seguro de que deseas eliminar esta carpeta?",
        "crash_title": "CatchEtude - Error Crítico",
        "crash_msg": "La aplicación se ha cerrado inesperadamente.",
        "lbl_traceback": "Detalles del error (Traceback):",
        "btn_restart_service": "Reiniciar servicio",
        "keep_in_downloads": "Mantener en descargas",
        "btn_keep": "Mantener",
        "msg_file_locked": "El archivo está ocupado. Espere a que se libere.",
        "last_file_open": "Abrir archivo reciente",
        "lbl_post_action": "Después de la acción",
        "post_action_open_file": "Abrir archivo",
        "post_action_open_folder": "Abrir la carpeta de destino",
        "post_action_none": "No hacer nada",
        "post_action_reset_notice": "La acción posterior sera restablecida automáticamente a 'No hacer nada'",
        "bulk_open_file_not_supported": "Abrir archivo tras la acción no está disponible para 'Mover todo a esta carpeta'. Se utilizará 'No hacer nada después'",
        "status_post_action_open_file": "El siguiente movimiento abrirá el archivo una sola vez.",
        "status_post_action_open_folder": "El siguiente movimiento abrirá la carpeta de destino una sola vez.",
        "status_post_action_none": "No se ejecutarán acciones posteriores.",
        "status_post_action_consumed": "La acción posterior fue consumida y volvió automáticamente a 'No hacer nada después'.",
        "status_bulk_open_file_disabled": "'Abrir archivo tras la acción' no está disponible para 'Mover todo a esta carpeta'. Se utilizará 'No hacer nada después'.",
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
        "tray_open_last": "Open last chosen folder",
        "tray_undo": "Undo last move",
        "tray_center": "Bring and center",
        "tray_show": "Show",
        "tray_hide": "Hide",
        "tray_rescan": "Rescan",
        "tray_logs": "View Logs",
        "tray_settings": "Settings",
        "tray_restart": "Restart Service",
        "tray_exit": "Close this service",
        "lang_name": "English",
        "lang_toggle": "ES",
        "btn_history": "Undo",
        "btn_header_delete": "Delete",
        "btn_hide": "Hide",
        "msg_pending_files": "There are pending files",
        "btn_show_again": "Show Again",
        "type_2": "Characters",
        "type_3": "Episodes",
        "type_4": "Music",
        "type_5": "Academic",
        "type_6": "Formalities",
        "type_7": "Linear Docs",
        "type_8": "Overworld",
        "menu_open_folder": "Open folder",
        "menu_move_all_in_folder": "Move all in this folder",
        "menu_create_folder": "Create new folder here",
        "menu_rename_folder": "Rename this folder",
        "menu_delete_folder": "Delete this empty folder",
        "menu_hidden_years": "Select hidden years",
        "dlg_create_title": "New folder",
        "dlg_create_label": "Folder name:",
        "dlg_rename_title": "Rename folder",
        "dlg_rename_label": "New name:",
        "dlg_delete_title": "Delete folder",
        "dlg_delete_confirm": "Are you sure you want to delete this folder?",
        "crash_title": "CatchEtude - Critical Error",
        "crash_msg": "The application closed unexpectedly.",
        "lbl_traceback": "Error details (Traceback):",
        "btn_restart_service": "Restart Service",
        "keep_in_downloads": "Keep in downloads",
        "btn_keep": "Keep",
        "msg_file_locked": "The file is in use. Wait until it is released.",
        "last_file_open": "Open the recent file",
        "lbl_post_action": "After the action:",
        "post_action_open_file": "Open file",
        "post_action_open_folder": "Open destination folder",
        "post_action_none": "Do nothing",
        "post_action_reset_notice": "The post action will be automatically reset to 'Do nothing'",
        "bulk open_file not_supported": "Open file after action is not available for 'Move everything to this folder'. 'Do nothing after' will be used.",
        "status_post_action_open_file": "The next action will open the file only once.",
        "status_post_action_open_folder": "The next action will open the destination folder only once.",
        "status_post_action_none": "No subsequent actions will be performed.",
        "status_post_action_consumed": "The subsequent action was consumed and automatically reverted to 'Do nothing after'.",
        "status_bulk_open_file_disabled": "'Open file after action' is not available for 'Move everything to this folder'. 'Do nothing after' will be used."
    }
}

class LocalizationManager:
    """
    Manages the current language and provides translated strings.
    Gestiona el idioma actual y proporciona cadenas traducidas.
    """
    def __init__(self):
        self.lang_path = config.LANG_PATH
        self.lang = self._load_lang()
        
    def _load_lang(self) -> str:
        if self.lang_path.exists():
            try:
                with open(self.lang_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    return config.get("lang", "es")
            except Exception:
                logging.exception("Error loading language config")
        return "es"

    def _save_lang(self):
        try:
            with open(self.lang_path, 'w', encoding='utf-8') as f:
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
