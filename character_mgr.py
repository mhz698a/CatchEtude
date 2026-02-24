"""
Module for managing character list loading and display.
Módulo para gestionar la carga y visualización de la lista de personajes.
"""

from dataclasses import dataclass
from datetime import datetime
import json
import logging
from pathlib import Path

from PyQt6 import QtCore, QtWidgets, QtNetwork
from PyQt6.QtCore import QModelIndex, Qt, pyqtSignal

# -----------------------
# Character dataclass
# -----------------------

@dataclass
class CharacterEntry:
    """
    Data structure for a character entry.
    Estructura de datos para una entrada de personaje.
    """
    year: int
    num: int
    alter: str
    name: str
    birthday_iso: str
    origin_age: int
    file_count: int
    total_size: int
    path: str = ""
    age_str: str = "" # Precalculated age for UI
    size_mb_str: str = "" # Precalculated size in MB for UI

class CharacterListModel(QtCore.QAbstractListModel):
    """
    Model for the character list in the UI.
    Communicates with character_service.py via IPC.
    """
    def __init__(self):
        super().__init__()
        self.items: list[CharacterEntry] = []
        self.active_generation = 0
        
        # Setup server to receive updates from the parallel service
        self.server = QtNetwork.QLocalServer(self)
        self.server.newConnection.connect(self._on_new_connection)
        QtNetwork.QLocalServer.removeServer("CatchEtudeCharacterClient")
        if not self.server.listen("CatchEtudeCharacterClient"):
            logging.error(f"Character Model Client Server could not start: {self.server.errorString()}")

    def clear_data(self):
        self.beginResetModel()
        self.items = []
        self.endResetModel()

    def request_characters(self, year: int, generation: int):
        self.active_generation = generation
        socket = QtNetwork.QLocalSocket()
        socket.connectToServer("CatchEtudeCharacterServer")
        if socket.waitForConnected(500):
            data = json.dumps({"cmd": "load", "year": year, "generation": generation})
            socket.write(data.encode('utf-8'))
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()
        else:
            logging.error("Failed to connect to Character Service")

    def _on_new_connection(self):
        socket = self.server.nextPendingConnection()
        socket.readyRead.connect(lambda: self._read_socket(socket))

    def _read_socket(self, socket):
        data = socket.readAll().data().decode('utf-8')
        try:
            msg = json.loads(data)
            cmd = msg.get("cmd")
            gen = msg.get("generation")
            
            if gen != self.active_generation:
                socket.disconnectFromServer()
                return

            if cmd == "batch":
                items_data = msg.get("items", [])
                new_items = [CharacterEntry(**d) for d in items_data]
                self.beginResetModel()
                self.items = new_items
                self.endResetModel()
            elif cmd == "update":
                idx = msg.get("index")
                item_data = msg.get("item")
                if 0 <= idx < len(self.items):
                    self.items[idx] = CharacterEntry(**item_data)
                    q_idx = self.index(idx)
                    self.dataChanged.emit(q_idx, q_idx)
                    
        except Exception:
            logging.exception("Error processing character update from service")
        socket.disconnectFromServer()

    def rowCount(self, parent=QModelIndex()):
        return len(self.items)

    def data(self, index, role):
        if not index.isValid():
            return None

        c = self.items[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return c.name if c.name != "_" else c.alter

        if role == Qt.ItemDataRole.UserRole:
            return c  # return full object

        return None

class CharacterDelegate(QtWidgets.QStyledItemDelegate):
    """
    Custom delegate for rendering character entries with metadata.
    Delegado personalizado para renderizar entradas de personajes con metadatos.
    """
    def paint(self, painter, option, index):
        painter.save()

        c: CharacterEntry = index.data(Qt.ItemDataRole.UserRole)
        rect = option.rect

        if option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, option.palette.highlight())

        # Line 1: Name and basic info
        try:
            birthday = datetime.fromisoformat(c.birthday_iso)
        except Exception:
            birthday = datetime(1970, 1, 1)
            
        birthday_fix = "" if not birthday or birthday.year == 1970 else f" · {birthday.strftime('%Y-%m-%d')}"
        num_char = f" · {c.num:02d}" if c.num != 0 else ""
        alter_sh = f"/{c.alter}" if c.name != '_' else ""
        
        painter.setPen(option.palette.text().color())
        painter.drawText(
            rect.adjusted(8, 4, -8, -rect.height() // 2),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{c.year}{num_char} · {c.name if c.name != '_' else c.alter}{alter_sh}{birthday_fix}"
        )
        
        # Line 2: Compact metadata (Age, Files, Size)
        real_age = f"{c.age_str} | " if c.age_str else ""
        
        distance = "" if c.origin_age == 0 else f"d: {(c.year - 2003) - c.origin_age} | "
        oring_age_fix = "" if c.origin_age == 0 else f"a: {c.origin_age} | "       
                        
        meta = (
            f"{real_age}"
            f"{distance}"
            f"{oring_age_fix}"
            f"Files: {c.file_count} | "
            f"{c.size_mb_str}"
        )
        
        secondary = option.palette.color(option.palette.ColorRole.PlaceholderText)
        painter.setPen(secondary)

        painter.drawText(
            rect.adjusted(8, rect.height() // 2, -8, -4),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            meta
        )

        painter.restore()

    def sizeHint(self, option, index):
        return QtCore.QSize(200, 54)
