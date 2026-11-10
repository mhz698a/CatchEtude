"""Small, queue-specific file rename dialog."""

from pathlib import Path

from PyQt6 import QtWidgets


class QueueRenameDialog(QtWidgets.QDialog):
    """Edit only the filename stem; the existing extension is kept unchanged."""

    _WINDOWS_RESERVED_NAMES = {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }

    def __init__(self, source_path: Path, localization, parent=None):
        super().__init__(parent)
        self.source_path = Path(source_path)
        self.loc = localization

        self.setWindowTitle(self.loc.get("dlg_queue_rename_title"))
        self.setModal(True)
        self.setFixedWidth(600)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        name_row = QtWidgets.QHBoxLayout()
        name_row.addWidget(QtWidgets.QLabel(self.loc.get("dlg_queue_rename_label")))
        self.name_edit = QtWidgets.QLineEdit(self.source_path.stem, self)
        self.name_edit.setClearButtonEnabled(True)
        name_row.addWidget(self.name_edit, 1)

        self.extension_label = QtWidgets.QLabel(self.source_path.suffix, self)
        self.extension_label.setMinimumWidth(54)
        name_row.addWidget(self.extension_label)
        layout.addLayout(name_row)

        self.error_label = QtWidgets.QLabel(self)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #e06c75;")
        self.error_label.hide()
        layout.addWidget(self.error_label)

        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.button_box.button(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
        ).setText(self.loc.get("dlg_queue_rename_apply"))
        self.button_box.button(
            QtWidgets.QDialogButtonBox.StandardButton.Cancel
        ).setText(self.loc.get("dlg_queue_rename_cancel"))
        self.button_box.accepted.connect(self._validate_and_accept)
        self.button_box.rejected.connect(self.reject)
        self.name_edit.returnPressed.connect(self._validate_and_accept)
        layout.addWidget(self.button_box)

        self.name_edit.selectAll()
        self.name_edit.setFocus()

    @property
    def new_stem(self) -> str:
        return self.name_edit.text().strip()

    def _validate_and_accept(self):
        name = self.new_stem
        if not name:
            self._show_error(self.loc.get("dlg_queue_rename_empty"))
            return

        invalid_characters = '<>:"/\\|?*'
        invalid = (
            any(ord(character) < 32 or character in invalid_characters for character in name)
            or name.endswith((".", " "))
            or name.split(".", 1)[0].upper() in self._WINDOWS_RESERVED_NAMES
        )
        if invalid:
            self._show_error(self.loc.get("dlg_queue_rename_invalid"))
            return

        self.accept()

    def _show_error(self, message: str):
        self.error_label.setText(message)
        self.error_label.show()

