"""
Folder Properties Dialog for CatchEtude.
Diálogo de propiedades de carpeta para CatchEtude.
"""

import os
from pathlib import Path
from typing import Optional

from PyQt6 import QtWidgets, QtCore, QtGui
from localization import LocalizationManager
from ui_utils_mgr import load_stylesheet

def scan_folder_stats(folder_path: Path) -> tuple[int, int]:
    """Scans a directory and returns (file_count, total_bytes)."""
    file_count = 0
    total_size = 0
    if not folder_path.exists() or not folder_path.is_dir():
        return file_count, total_size

    try:
        for root, _, files in os.walk(folder_path):
            for fname in files:
                if fname.lower() in ("desktop.ini", "thumbs.db"):
                    continue
                file_count += 1
                try:
                    total_size += os.path.getsize(os.path.join(root, fname))
                except OSError:
                    pass
    except Exception:
        pass

    return file_count, total_size

def format_bytes(total_bytes: int) -> str:
    """Formats bytes into human readable MB / GB string with exact bytes in parentheses."""
    if total_bytes < 1024 * 1024:
        kb = total_bytes / 1024
        return f"{kb:.1f} KB ({total_bytes:,} bytes)"
    elif total_bytes < 1024 * 1024 * 1024:
        mb = total_bytes / (1024 * 1024)
        return f"{mb:.1f} MB ({total_bytes:,} bytes)"
    else:
        gb = total_bytes / (1024 * 1024 * 1024)
        return f"{gb:.2f} GB ({total_bytes:,} bytes)"


class FolderPropertiesDialog(QtWidgets.QDialog):
    """
    Dialog displaying detailed properties of a subfolder,
    including file count, total size, and optional character metadata.
    """
    def __init__(self, folder_path: Path, char_entry: Optional[object] = None, parent=None, loc: Optional[LocalizationManager] = None):
        super().__init__(parent)
        self.folder_path = folder_path
        self.char_entry = char_entry
        self.loc = loc or LocalizationManager()

        self.setWindowTitle(f"{self.loc.get('dlg_properties_title')} - {folder_path.name}")
        self.setMinimumWidth(420)
        self.setModal(True)

        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # Header Title
        header_lbl = QtWidgets.QLabel(self.folder_path.name)
        font = header_lbl.font()
        font.setPointSize(14)
        font.setBold(True)
        header_lbl.setFont(font)
        layout.addWidget(header_lbl)

        # Separator line
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        layout.addWidget(line)

        # Form Layout for Properties
        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop)
        form.setSpacing(8)

        # Scan folder stats
        file_count, total_bytes = scan_folder_stats(self.folder_path)
        if self.char_entry and file_count == 0:
            if hasattr(self.char_entry, "file_count") and self.char_entry.file_count:
                file_count = self.char_entry.file_count
            if hasattr(self.char_entry, "total_size") and self.char_entry.total_size:
                total_bytes = self.char_entry.total_size

        formatted_size = format_bytes(total_bytes)

        # General properties
        form.addRow(self._make_label(self.loc.get("lbl_prop_name"), True), self._make_label(self.folder_path.name))
        form.addRow(self._make_label(self.loc.get("lbl_prop_path"), True), self._make_label(str(self.folder_path)))
        form.addRow(self._make_label(self.loc.get("lbl_prop_files"), True), self._make_label(str(file_count)))
        form.addRow(self._make_label(self.loc.get("lbl_prop_size"), True), self._make_label(formatted_size))

        # Character metadata if available
        if self.char_entry:
            # Separator in form
            c = self.char_entry
            if hasattr(c, "year") and c.year:
                form.addRow(self._make_label(self.loc.get("lbl_prop_year"), True), self._make_label(str(c.year)))
            if hasattr(c, "num") and c.num is not None:
                form.addRow(self._make_label(self.loc.get("lbl_prop_num"), True), self._make_label(f"{c.num:02d}" if c.num != 0 else "0"))
            if hasattr(c, "name") and c.name:
                char_name = c.name if c.name != "_" else getattr(c, "alter", "")
                form.addRow(self._make_label(self.loc.get("lbl_prop_char_name"), True), self._make_label(char_name))
            if hasattr(c, "alter") and c.alter and c.alter != "_":
                form.addRow(self._make_label(self.loc.get("lbl_prop_alter"), True), self._make_label(c.alter))
            if hasattr(c, "birthday_iso") and c.birthday_iso:
                form.addRow(self._make_label(self.loc.get("lbl_prop_birthday"), True), self._make_label(c.birthday_iso))
            if hasattr(c, "age_str") and c.age_str:
                form.addRow(self._make_label(self.loc.get("lbl_prop_age"), True), self._make_label(c.age_str))

        layout.addLayout(form)

        # Spacer and Close Button
        layout.addStretch()

        btn_box = QtWidgets.QHBoxLayout()
        btn_box.addStretch()

        btn_close = QtWidgets.QPushButton(self.loc.get("btn_close"))
        btn_close.setFixedWidth(100)
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)

        layout.addLayout(btn_box)

    def _make_label(self, text: str, bold: bool = False) -> QtWidgets.QLabel:
        lbl = QtWidgets.QLabel(text)
        lbl.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
        if bold:
            font = lbl.font()
            font.setBold(True)
            lbl.setFont(font)
        return lbl
