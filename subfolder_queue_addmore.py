"""
Subfolder Queue AddMore Module for CatchEtude.
Modulo para escanear y agregar archivos de subcarpetas a la cola de descargas.
"""

import os
import logging
from pathlib import Path
from PyQt6 import QtWidgets

from utils import is_temporary

def populate_add_to_queue_menu(parent_widget, menu: QtWidgets.QMenu, folder_path: Path, state_manager, status_callback=None):
    """
    Agrega el submenu 'Añadir a la cola...' con las opciones solicitadas:
    0. Separador
    1. Los primeros 5 archivos
    2. Los primeros 10 archivos
    3. Los primeros 50 archivos
    4. Los primeros 100 archivos
    5. Toda la carpeta
    """
    menu.addSeparator()
    sub_menu = menu.addMenu("Añadir a la cola...")

    options = [
        ("Los primeros 5 archivos", 5),
        ("Los primeros 10 archivos", 10),
        ("Los primeros 50 archivos", 50),
        ("Los primeros 100 archivos", 100),
        ("Toda la carpeta", -1),
    ]

    for label, count in options:
        act = sub_menu.addAction(label)
        act.triggered.connect(
            lambda checked=False, c=count: handle_add_to_queue(parent_widget, folder_path, c, state_manager, status_callback)
        )


def handle_add_to_queue(parent_widget, folder_path: Path, count: int, state_manager, status_callback=None):
    """
    Escanea la subcarpeta y encola la cantidad de archivos especificada.
    """
    if not folder_path or not folder_path.exists() or not folder_path.is_dir():
        return

    try:
        all_files = []
        for entry in folder_path.rglob("*"):
            if entry.is_file() and not is_temporary(entry):
                all_files.append(entry)

        all_files.sort()
        total_found = len(all_files)

        if total_found == 0:
            if status_callback:
                status_callback("No se encontraron archivos en la carpeta.")
            return

        if count == -1:  # Toda la carpeta
            if total_found > 250:
                res = QtWidgets.QMessageBox.question(
                    parent_widget,
                    "Confirmación",
                    "Esta carpeta contiene más de 250 archivos y puede tomar tiempo en añadir todo a la cola de descargas ¿Desea continuar?",
                    QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                    QtWidgets.QMessageBox.StandardButton.No
                )
                if res != QtWidgets.QMessageBox.StandardButton.Yes:
                    return
            files_to_add = all_files
        else:
            files_to_add = all_files[:count]
            if total_found < count and status_callback:
                status_callback(f"Solo se encontraron {total_found} archivos en la carpeta.")

        if files_to_add:
            state_manager.enqueue_files(files_to_add)
            if status_callback and (count == -1 or total_found >= count):
                status_callback(f"Se añadieron {len(files_to_add)} archivos a la cola.")

    except Exception:
        logging.exception(f"Error al añadir archivos de la subcarpeta {folder_path} a la cola")
