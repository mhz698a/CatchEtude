"""Visual administrator for CatchEtude classification definitions."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

import config
from classification_registry import ClassificationRegistry
from decision_dispatcher import DecisionDispatcher
from decision_editor_model import (
    DecisionEditorModel,
    validate_decision_configuration,
)


class DecisionManagerDialog(QtWidgets.QDialog):
    """Edit the visual and routing settings of classification definitions."""

    def __init__(
        self,
        registry: ClassificationRegistry,
        loc,
        parent: QtWidgets.QWidget | None = None,
    ):
        super().__init__(parent)
        self.registry = registry
        self.loc = loc
        self.model = DecisionEditorModel(registry.decisions)
        self._dirty = False
        self._loading_editor = False
        self._current_editor_id: int | None = None
        self._source_fingerprint = registry.get_config_fingerprint()

        self.setWindowTitle(self.loc.get("decision_manager_title"))
        self.setWindowIcon(QtGui.QIcon(config.ICON_PATH))
        self.setMinimumSize(1060, 680)
        self.resize(1180, 760)
        self.setModal(True)

        self._build_ui()
        self._refresh_list()

    def _build_ui(self) -> None:
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 14)
        root.setSpacing(12)

        title = QtWidgets.QLabel(self.loc.get("decision_manager_title"))
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        subtitle = QtWidgets.QLabel(self.loc.get("decision_manager_subtitle"))
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: palette(mid);")
        root.addWidget(title)
        root.addWidget(subtitle)

        content = QtWidgets.QHBoxLayout()
        content.setSpacing(14)

        left = QtWidgets.QVBoxLayout()
        left.addWidget(QtWidgets.QLabel(self.loc.get("decision_manager_list")))
        self.list_widget = QtWidgets.QListWidget()
        self.list_widget.setIconSize(QtCore.QSize(30, 30))
        self.list_widget.setSpacing(3)
        self.list_widget.setMinimumWidth(310)
        self.list_widget.currentItemChanged.connect(self._on_current_item_changed)
        self.list_widget.itemChanged.connect(self._on_item_changed)
        left.addWidget(self.list_widget, 1)

        action_row = QtWidgets.QHBoxLayout()
        self.btn_new = QtWidgets.QPushButton(self.loc.get("decision_manager_new"))
        self.btn_duplicate = QtWidgets.QPushButton(
            self.loc.get("decision_manager_duplicate")
        )
        self.btn_remove = QtWidgets.QPushButton(
            self.loc.get("decision_manager_remove")
        )
        self.btn_new.clicked.connect(self._add_decision)
        self.btn_duplicate.clicked.connect(self._duplicate_decision)
        self.btn_remove.clicked.connect(self._remove_decision)
        action_row.addWidget(self.btn_new)
        action_row.addWidget(self.btn_duplicate)
        action_row.addWidget(self.btn_remove)
        left.addLayout(action_row)

        order_row = QtWidgets.QHBoxLayout()
        self.btn_up = QtWidgets.QPushButton(self.loc.get("decision_manager_up"))
        self.btn_down = QtWidgets.QPushButton(self.loc.get("decision_manager_down"))
        self.btn_up.clicked.connect(lambda: self._move_decision(-1))
        self.btn_down.clicked.connect(lambda: self._move_decision(1))
        order_row.addWidget(self.btn_up)
        order_row.addWidget(self.btn_down)
        order_row.addStretch(1)
        left.addLayout(order_row)
        content.addLayout(left, 3)

        right = QtWidgets.QVBoxLayout()
        details_box = QtWidgets.QGroupBox(self.loc.get("decision_manager_details"))
        details_form = QtWidgets.QFormLayout(details_box)
        self.detail_id = QtWidgets.QLabel("—")
        self.detail_order = QtWidgets.QLabel("—")
        self.detail_state = QtWidgets.QLabel("—")
        for label in (self.detail_id, self.detail_order, self.detail_state):
            label.setTextInteractionFlags(
                QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
            )
        details_form.addRow("ID", self.detail_id)
        details_form.addRow(self.loc.get("decision_manager_order"), self.detail_order)
        details_form.addRow(self.loc.get("decision_manager_status"), self.detail_state)
        right.addWidget(details_box)

        self.editor_tabs = QtWidgets.QTabWidget()
        self._build_general_tab()
        self._build_destination_tab()
        self._build_behavior_tab()
        right.addWidget(self.editor_tabs, 1)
        content.addLayout(right, 5)
        root.addLayout(content, 1)

        footer = QtWidgets.QHBoxLayout()
        self.status_label = QtWidgets.QLabel(
            self.loc.get("decision_manager_unsaved_hint")
        )
        self.status_label.setStyleSheet("color: palette(mid);")
        footer.addWidget(self.status_label, 1)
        self.btn_cancel = QtWidgets.QPushButton(
            self.loc.get("decision_manager_cancel")
        )
        self.btn_save = QtWidgets.QPushButton(
            self.loc.get("decision_manager_save")
        )
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save.clicked.connect(self._save)
        self.btn_save.setEnabled(False)
        footer.addWidget(self.btn_cancel)
        footer.addWidget(self.btn_save)
        root.addLayout(footer)

    def _build_general_tab(self) -> None:
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setMaxLength(120)
        self.icon_combo = QtWidgets.QComboBox()
        self._populate_icon_combo()
        self.handler_value = QtWidgets.QLabel("—")
        self.handler_note = QtWidgets.QLabel()
        self.handler_note.setWordWrap(True)
        form.addRow(self.loc.get("decision_manager_name"), self.name_edit)
        form.addRow(self.loc.get("decision_manager_icon"), self.icon_combo)
        form.addRow(self.loc.get("decision_manager_handler"), self.handler_value)
        form.addRow("", self.handler_note)
        self.editor_tabs.addTab(tab, self.loc.get("decision_manager_tab_general"))
        self.name_edit.textChanged.connect(self._on_form_changed)
        self.icon_combo.currentIndexChanged.connect(self._on_form_changed)

    def _populate_icon_combo(self) -> None:
        self.icon_combo.clear()
        self.icon_combo.addItem(self.loc.get("decision_manager_no_icon"), "")
        assets_dir = Path(config.APP_DIR) / "assets"
        if not assets_dir.is_dir():
            return
        for asset in sorted(assets_dir.iterdir(), key=lambda path: path.name.casefold()):
            if asset.is_file() and asset.suffix.lower() in {".png", ".ico"}:
                self.icon_combo.addItem(QtGui.QIcon(str(asset)), asset.stem, asset.name)

    def _add_variable_menu(
        self,
        button: QtWidgets.QToolButton,
        line_edit: QtWidgets.QLineEdit,
    ) -> None:
        menu = QtWidgets.QMenu(button)
        tokens = (
            "BASE_INTERNAL", "ONEDRIVE_DOCS", "ONEDRIVE_DOCTOS_FAMILIA",
            "IMAGES_FOLDER", "MUSIC_FOLDER", "OVERWORLD_FOLDER",
            "ACROBAT_FOLDER", "year", "year_prefix", "mtime_year", "mtime_month",
        )
        for token in tokens:
            action = menu.addAction("{" + token + "}")
            action.triggered.connect(
                lambda checked=False, value=token, editor=line_edit:
                editor.insert("{" + value + "}")
            )
        button.setMenu(menu)
        button.setPopupMode(QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)

    def _path_editor(
        self,
        line_edit: QtWidgets.QLineEdit,
        browse: bool = False,
    ) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(line_edit, 1)
        if browse:
            button = QtWidgets.QToolButton()
            button.setText("…")
            button.setToolTip(self.loc.get("decision_manager_browse_folder"))
            button.clicked.connect(lambda: self._browse_path(line_edit))
            row.addWidget(button)
        variables = QtWidgets.QToolButton()
        variables.setText("{x}")
        variables.setToolTip(self.loc.get("decision_manager_insert_variable"))
        self._add_variable_menu(variables, line_edit)
        row.addWidget(variables)
        return container

    def _browse_path(self, editor: QtWidgets.QLineEdit) -> None:
        current = editor.text().strip()
        initial = current if current and Path(current).is_dir() else str(config.BASE_INTERNAL)
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self, self.loc.get("decision_manager_browse_folder"), initial
        )
        if selected:
            editor.setText(selected)

    def _build_destination_tab(self) -> None:
        self.destination_tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(self.destination_tab)

        self.year_mode_combo = QtWidgets.QComboBox()
        self.year_mode_combo.addItem(
            self.loc.get("decision_manager_year_none"), "none"
        )
        self.year_mode_combo.addItem(
            self.loc.get("decision_manager_year_required"), "required"
        )
        self.base_path_edit = QtWidgets.QLineEdit()

        self.folder_source_combo = QtWidgets.QComboBox()
        self.folder_source_combo.addItem(
            self.loc.get("decision_manager_folder_source_filesystem"), "filesystem"
        )
        self.folder_source_combo.addItem(
            self.loc.get("decision_manager_folder_source_none"), "none"
        )
        self.folder_contains_edit = QtWidgets.QLineEdit()
        self.folder_fallback_edit = QtWidgets.QLineEdit()
        self.requires_internal_cb = QtWidgets.QCheckBox(
            self.loc.get("decision_manager_requires_internal")
        )

        preview_row = QtWidgets.QWidget()
        preview_layout = QtWidgets.QHBoxLayout(preview_row)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview_year = QtWidgets.QSpinBox()
        self.preview_year.setRange(1990, 2100)
        self.preview_year.setValue(config.CURRENT_YEAR)
        self.preview_button = QtWidgets.QPushButton(
            self.loc.get("decision_manager_preview")
        )
        preview_layout.addWidget(self.preview_year)
        preview_layout.addWidget(self.preview_button)
        preview_layout.addStretch(1)

        self.preview_label = QtWidgets.QLabel(
            self.loc.get("decision_manager_preview_hint")
        )
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )

        form.addRow(self.loc.get("decision_manager_year_mode"), self.year_mode_combo)
        form.addRow(
            self.loc.get("decision_manager_base_path"),
            self._path_editor(self.base_path_edit, True),
        )
        form.addRow(
            self.loc.get("decision_manager_folder_source"),
            self.folder_source_combo,
        )
        form.addRow(
            self.loc.get("decision_manager_folder_contains"),
            self._path_editor(self.folder_contains_edit),
        )
        form.addRow(
            self.loc.get("decision_manager_folder_fallback"),
            self._path_editor(self.folder_fallback_edit, True),
        )
        form.addRow("", self.requires_internal_cb)
        form.addRow(self.loc.get("decision_manager_preview_year"), preview_row)
        form.addRow(self.loc.get("decision_manager_preview_result"), self.preview_label)
        self.editor_tabs.addTab(
            self.destination_tab, self.loc.get("decision_manager_tab_destination")
        )

        self.year_mode_combo.currentIndexChanged.connect(self._on_form_changed)
        self.base_path_edit.textChanged.connect(self._on_form_changed)
        self.folder_source_combo.currentIndexChanged.connect(
            self._on_folder_source_changed
        )
        self.folder_contains_edit.textChanged.connect(self._on_form_changed)
        self.folder_fallback_edit.textChanged.connect(self._on_form_changed)
        self.requires_internal_cb.toggled.connect(self._on_form_changed)
        self.preview_button.clicked.connect(self._preview_path)

    def _build_behavior_tab(self) -> None:
        tab = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(tab)
        self.second_line_combo = QtWidgets.QComboBox()
        self.second_line_combo.addItem(
            self.loc.get("decision_manager_second_none"), None
        )
        self.second_line_combo.addItem(
            self.loc.get("decision_manager_second_character"), "character_metadata"
        )
        self.second_line_combo.addItem(
            self.loc.get("decision_manager_second_last_file"), "last_file"
        )
        self.second_line_combo.addItem(
            self.loc.get("decision_manager_second_overworld"), "overworld_metadata"
        )
        self.allow_create_cb = QtWidgets.QCheckBox(
            self.loc.get("decision_manager_allow_create")
        )
        self.allow_rename_cb = QtWidgets.QCheckBox(
            self.loc.get("decision_manager_allow_rename")
        )
        self.allow_delete_cb = QtWidgets.QCheckBox(
            self.loc.get("decision_manager_allow_delete")
        )
        self.behavior_note = QtWidgets.QLabel(
            self.loc.get("decision_manager_behavior_note")
        )
        self.behavior_note.setWordWrap(True)

        form.addRow(self.loc.get("decision_manager_second_line"), self.second_line_combo)
        form.addRow("", self.allow_create_cb)
        form.addRow("", self.allow_rename_cb)
        form.addRow("", self.allow_delete_cb)
        form.addRow("", self.behavior_note)
        self.editor_tabs.addTab(tab, self.loc.get("decision_manager_tab_behavior"))

        self.second_line_combo.currentIndexChanged.connect(self._on_form_changed)
        self.allow_create_cb.toggled.connect(self._on_form_changed)
        self.allow_rename_cb.toggled.connect(self._on_form_changed)
        self.allow_delete_cb.toggled.connect(self._on_form_changed)

    def _decision_name(self, decision: dict[str, Any]) -> str:
        return self.registry.get_decision_name(
            decision, self.loc.current_lang(), self.loc
        )

    def _handler_label(self, handler: str) -> str:
        labels = {
            "keep": self.loc.get("decision_manager_handler_keep"),
            "linear_docs": self.loc.get("decision_manager_handler_linear"),
            "move_to_subfolder": self.loc.get(
                "decision_manager_handler_subfolder"
            ),
        }
        return labels.get(handler, str(handler))

    def _current_id(self) -> int | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        try:
            return int(item.data(QtCore.Qt.ItemDataRole.UserRole))
        except (TypeError, ValueError):
            return None

    def _decision_icon(self, decision: dict[str, Any]) -> QtGui.QIcon:
        icon_name = str(decision.get("icon") or "").strip()
        if icon_name:
            icon_path = Path(config.APP_DIR) / "assets" / icon_name
            if icon_path.is_file():
                return QtGui.QIcon(str(icon_path))
        fallback = QtGui.QIcon.fromTheme("folder")
        return fallback if not fallback.isNull() else QtGui.QIcon(config.ICON_PATH)

    def _refresh_list(self, selected_id: int | None = None) -> None:
        if selected_id is None:
            selected_id = self._current_id()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        selected_row = -1

        for row, decision in enumerate(self.model.decisions):
            item = QtWidgets.QListWidgetItem(
                self._decision_icon(decision),
                f"{self._decision_name(decision)}\nID {decision['id']} · "
                f"{self._handler_label(decision.get('handler', ''))}",
            )
            item.setData(QtCore.Qt.ItemDataRole.UserRole, decision["id"])
            item.setFlags(
                item.flags()
                | QtCore.Qt.ItemFlag.ItemIsUserCheckable
                | QtCore.Qt.ItemFlag.ItemIsEnabled
                | QtCore.Qt.ItemFlag.ItemIsSelectable
            )
            item.setCheckState(
                QtCore.Qt.CheckState.Checked
                if decision.get("enabled", True)
                else QtCore.Qt.CheckState.Unchecked
            )
            item.setToolTip(
                self.loc.get("decision_manager_enabled")
                if decision.get("enabled", True)
                else self.loc.get("decision_manager_disabled")
            )
            item.setSizeHint(QtCore.QSize(0, 54))
            self.list_widget.addItem(item)
            if decision["id"] == selected_id:
                selected_row = row

        if selected_row < 0 and self.list_widget.count():
            selected_row = 0
        if selected_row >= 0:
            self.list_widget.setCurrentRow(selected_row)
        self.list_widget.blockSignals(False)
        self._refresh_details()
        self._refresh_controls()
        self._load_editor(self.model.get_decision(self._current_id()))

    def _refresh_details(self) -> None:
        decision = self.model.get_decision(self._current_id())
        if decision is None:
            values = ("—", "—", "—")
        else:
            values = (
                str(decision["id"]),
                str(decision.get("order", 0)),
                self.loc.get(
                    "decision_manager_enabled"
                    if decision.get("enabled", True)
                    else "decision_manager_disabled"
                ),
            )
        for widget, value in zip(
            (self.detail_id, self.detail_order, self.detail_state), values
        ):
            widget.setText(value)

    def _refresh_controls(self) -> None:
        decision = self.model.get_decision(self._current_id())
        index = next(
            (
                i for i, item in enumerate(self.model.decisions)
                if item.get("id") == self._current_id()
            ),
            -1,
        )
        has_selection = decision is not None
        protected = has_selection and decision.get("handler") == "keep"
        self.btn_duplicate.setEnabled(has_selection and not protected)
        self.btn_remove.setEnabled(has_selection and not protected)
        self.btn_up.setEnabled(has_selection and index > 0)
        self.btn_down.setEnabled(
            has_selection and index >= 0
            and index < len(self.model.decisions) - 1
        )
        tooltip = (
            self.loc.get("decision_manager_keep_protected") if protected else ""
        )
        self.btn_duplicate.setToolTip(tooltip)
        self.btn_remove.setToolTip(tooltip)

    def _on_form_changed(self, *args) -> None:
        if not self._loading_editor and self._current_editor_id is not None:
            self._mark_dirty()

    def _load_editor(self, decision: dict[str, Any] | None) -> None:
        self._loading_editor = True
        self._current_editor_id = decision.get("id") if decision else None
        if decision is None:
            self.name_edit.clear()
            self.handler_value.setText("—")
            self._update_editor_capabilities(None)
            self._loading_editor = False
            return

        self.name_edit.setText(self._decision_name(decision))
        icon_name = str(decision.get("icon") or "")
        icon_index = self.icon_combo.findData(icon_name)
        if icon_index < 0 and icon_name:
            self.icon_combo.addItem(
                f"{icon_name} ({self.loc.get('decision_manager_missing_icon')})",
                icon_name,
            )
            icon_index = self.icon_combo.count() - 1
        self.icon_combo.setCurrentIndex(max(0, icon_index))

        handler = decision.get("handler", "move_to_subfolder")
        self.handler_value.setText(self._handler_label(handler))
        self.year_mode_combo.setCurrentIndex(
            max(0, self.year_mode_combo.findData(decision.get("year_mode", "none")))
        )
        self.base_path_edit.setText(str(decision.get("base_path") or ""))
        self.folder_source_combo.setCurrentIndex(
            max(0, self.folder_source_combo.findData(decision.get("folder_source", "none")))
        )
        self.folder_contains_edit.setText(str(decision.get("folder_contains") or ""))
        self.folder_fallback_edit.setText(str(decision.get("folder_fallback") or ""))
        self.requires_internal_cb.setChecked(
            bool(decision.get("requires_internal", False))
        )
        self.second_line_combo.setCurrentIndex(
            max(0, self.second_line_combo.findData(decision.get("behaviour_second_line")))
        )
        self.allow_create_cb.setChecked(bool(decision.get("allow_create", False)))
        self.allow_rename_cb.setChecked(bool(decision.get("allow_rename", False)))
        self.allow_delete_cb.setChecked(bool(decision.get("allow_delete", False)))
        self._refresh_details()
        self._update_editor_capabilities(decision)
        self.preview_label.setText(self.loc.get("decision_manager_preview_hint"))
        self._loading_editor = False

    def _update_editor_capabilities(self, decision: dict[str, Any] | None) -> None:
        handler = decision.get("handler") if decision else None
        is_keep = handler == "keep"
        is_linear = handler == "linear_docs"
        is_folder = handler == "move_to_subfolder"
        self.destination_tab.setEnabled(decision is not None and not is_keep)
        self.handler_note.setVisible(is_keep or is_linear)
        if is_keep:
            self.handler_note.setText(
                self.loc.get("decision_manager_keep_handler_note")
            )
        elif is_linear:
            self.handler_note.setText(
                self.loc.get("decision_manager_linear_handler_note")
            )

        self.name_edit.setEnabled(decision is not None)
        self.icon_combo.setEnabled(decision is not None)
        self.year_mode_combo.setEnabled(is_folder)
        self.base_path_edit.setEnabled(is_folder or is_linear)
        self.folder_source_combo.setEnabled(is_folder)
        source_is_filesystem = (
            is_folder and self.folder_source_combo.currentData() == "filesystem"
        )
        self.folder_contains_edit.setEnabled(source_is_filesystem)
        self.folder_fallback_edit.setEnabled(source_is_filesystem)
        self.requires_internal_cb.setEnabled(is_folder or is_linear)
        self.second_line_combo.setEnabled(source_is_filesystem)
        for checkbox in (
            self.allow_create_cb, self.allow_rename_cb, self.allow_delete_cb
        ):
            checkbox.setEnabled(source_is_filesystem)
        self.preview_button.setEnabled(is_folder or is_linear)
        self.preview_year.setEnabled(is_folder or is_linear)

    def _localized_name_value(
        self,
        decision: dict[str, Any],
        edited_name: str,
    ) -> dict[str, str]:
        from localization import STRINGS

        existing = decision.get("name")
        if isinstance(existing, dict):
            names = {
                language: value
                for language, value in existing.items()
                if isinstance(value, str) and value.strip()
            }
        elif isinstance(existing, str) and existing.strip():
            names = {"es": existing, "en": existing}
        else:
            names = {}

        key = decision.get("name_key")
        fallback = next(iter(names.values()), edited_name)
        for language in ("es", "en"):
            if not names.get(language):
                names[language] = (
                    STRINGS.get(language, {}).get(key)
                    or fallback
                    or edited_name
                )
        names[self.loc.current_lang()] = edited_name
        return names

    def _collect_editor_fields(self, decision: dict[str, Any]) -> dict[str, Any]:
        handler = decision.get("handler")
        fields: dict[str, Any] = {}
        edited_name = self.name_edit.text().strip()
        if not edited_name:
            raise ValueError(self.loc.get("decision_manager_name_required"))
        if edited_name != self._decision_name(decision):
            fields["name"] = self._localized_name_value(decision, edited_name)

        icon = self.icon_combo.currentData() or None
        if icon != (decision.get("icon") or None):
            fields["icon"] = icon
        if handler == "keep":
            return fields

        fields["base_path"] = self.base_path_edit.text().strip() or None
        fields["year_mode"] = (
            "required" if handler == "linear_docs"
            else self.year_mode_combo.currentData()
        )
        fields["requires_internal"] = self.requires_internal_cb.isChecked()

        if handler == "move_to_subfolder":
            source = self.folder_source_combo.currentData()
            fields["folder_source"] = source
            fields["folder_contains"] = (
                self.folder_contains_edit.text().strip() or None
                if source == "filesystem" else None
            )
            fields["folder_fallback"] = (
                self.folder_fallback_edit.text().strip() or None
                if source == "filesystem" else None
            )
            fields["behaviour_second_line"] = (
                self.second_line_combo.currentData()
                if source == "filesystem" else None
            )
            fields["allow_create"] = (
                self.allow_create_cb.isChecked() if source == "filesystem" else False
            )
            fields["allow_rename"] = (
                self.allow_rename_cb.isChecked() if source == "filesystem" else False
            )
            fields["allow_delete"] = (
                self.allow_delete_cb.isChecked() if source == "filesystem" else False
            )
        else:
            fields.update({
                "folder_source": "none",
                "folder_contains": None,
                "folder_fallback": None,
                "behaviour_second_line": None,
                "allow_create": False,
                "allow_rename": False,
                "allow_delete": False,
            })
        return fields

    def _update_list_item(self, decision: dict[str, Any]) -> None:
        for row in range(self.list_widget.count()):
            item = self.list_widget.item(row)
            if item.data(QtCore.Qt.ItemDataRole.UserRole) != decision.get("id"):
                continue
            item.setText(
                f"{self._decision_name(decision)}\nID {decision['id']} · "
                f"{self._handler_label(decision.get('handler', ''))}"
            )
            item.setIcon(self._decision_icon(decision))
            return

    def _commit_current_editor(self) -> bool:
        decision = self.model.get_decision(self._current_editor_id)
        if decision is None:
            return True
        try:
            fields = self._collect_editor_fields(decision)
            changed = self.model.update_fields(decision["id"], fields)
        except (TypeError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self,
                self.loc.get("decision_manager_title"),
                self.loc.get("decision_manager_invalid_editor_value").format(error=str(exc)),
            )
            self.name_edit.setFocus()
            return False
        if changed:
            self._mark_dirty()
            self._update_list_item(self.model.get_decision(decision["id"]))
        return True

    def _on_current_item_changed(self, current, previous) -> None:
        if not self._commit_current_editor():
            self.list_widget.blockSignals(True)
            self.list_widget.setCurrentItem(previous)
            self.list_widget.blockSignals(False)
            return
        self._refresh_details()
        self._refresh_controls()
        decision_id = (
            current.data(QtCore.Qt.ItemDataRole.UserRole) if current else None
        )
        self._load_editor(self.model.get_decision(decision_id))

    def _on_item_changed(self, item: QtWidgets.QListWidgetItem) -> None:
        decision_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        enabled = item.checkState() == QtCore.Qt.CheckState.Checked
        try:
            self.model.set_enabled(int(decision_id), enabled)
        except (KeyError, TypeError, ValueError):
            return
        self._mark_dirty()
        self._refresh_details()

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.btn_save.setEnabled(True)
        self.status_label.setText(
            self.loc.get("decision_manager_changes_pending")
        )

    def _add_decision(self) -> None:
        if not self._commit_current_editor():
            return
        decision_id = self.model.add(self.loc.get("decision_manager_new_name"))
        self._refresh_list(decision_id)
        self._mark_dirty()

    def _duplicate_decision(self) -> None:
        if not self._commit_current_editor():
            return
        decision_id = self._current_id()
        decision = self.model.get_decision(decision_id)
        if decision is None or decision.get("handler") == "keep":
            return
        new_name = (
            f"{self.loc.get('decision_manager_copy_prefix')} "
            f"{self._decision_name(decision)}"
        )
        try:
            duplicate_id = self.model.duplicate(decision_id, new_name)
        except (KeyError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self, self.loc.get("decision_manager_title"), str(exc)
            )
            return
        self._refresh_list(duplicate_id)
        self._mark_dirty()

    def _remove_decision(self) -> None:
        if not self._commit_current_editor():
            return
        decision_id = self._current_id()
        decision = self.model.get_decision(decision_id)
        if decision is None or decision.get("handler") == "keep":
            return
        message = self.loc.get("decision_manager_confirm_delete").format(
            name=self._decision_name(decision)
        )
        answer = QtWidgets.QMessageBox.question(
            self,
            self.loc.get("decision_manager_confirm_delete_title"),
            message,
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        try:
            self.model.delete(decision_id)
        except (KeyError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self, self.loc.get("decision_manager_title"), str(exc)
            )
            return
        self._refresh_list()
        self._mark_dirty()

    def _move_decision(self, offset: int) -> None:
        if not self._commit_current_editor():
            return
        decision_id = self._current_id()
        if decision_id is None:
            return
        try:
            self.model.move(decision_id, offset)
        except (KeyError, ValueError):
            return
        self._refresh_list(decision_id)
        self._mark_dirty()

    def _on_folder_source_changed(self, _index: int) -> None:
        self._on_form_changed()
        self._update_editor_capabilities(
            self.model.get_decision(self._current_editor_id)
        )

    def _preview_path(self) -> None:
        decision = self.model.get_decision(self._current_editor_id)
        if decision is None:
            return
        candidate = copy.deepcopy(decision)
        try:
            candidate.update(self._collect_editor_fields(candidate))
            validate_decision_configuration(candidate)
            if any(
                token in str(candidate.get(key) or "")
                for key in ("base_path", "folder_contains", "folder_fallback")
                for token in ("{mtime_year}", "{mtime_month}")
            ):
                self.preview_label.setText(
                    self.loc.get("decision_manager_preview_requires_source")
                )
                return
            dispatcher = DecisionDispatcher(registry=self.registry)
            year = (
                self.preview_year.value()
                if candidate.get("year_mode") == "required" else None
            )
            resolved = dispatcher.resolve_base_path(candidate, year)
        except (TypeError, ValueError, OSError) as exc:
            self.preview_label.setText(
                self.loc.get("decision_manager_preview_error").format(error=str(exc))
            )
            return
        if resolved is None:
            self.preview_label.setText(
                self.loc.get("decision_manager_preview_unavailable")
            )
            return
        status_key = (
            "decision_manager_preview_exists"
            if resolved.is_dir()
            else "decision_manager_preview_not_exists"
        )
        self.preview_label.setText(
            f"{resolved}\n{self.loc.get(status_key)}"
        )

    def _save(self) -> None:
        if not self._commit_current_editor():
            return
        if self.registry.load_error:
            QtWidgets.QMessageBox.critical(
                self,
                self.loc.get("decision_manager_title"),
                self.loc.get("decision_manager_config_unreadable").format(
                    error=self.registry.load_error
                ),
            )
            return
        if not self._dirty:
            self.accept()
            return
        candidate = self.model.snapshot()
        try:
            for decision in candidate:
                validate_decision_configuration(decision)
            ClassificationRegistry.validate_decisions(candidate)
        except (TypeError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self, self.loc.get("decision_manager_title"), str(exc)
            )
            return

        previous = copy.deepcopy(self.registry.decisions)
        self.registry.decisions = candidate
        if not self.registry.save_config(
            expected_fingerprint=self._source_fingerprint
        ):
            self.registry.decisions = previous
            if self.registry.last_save_error == "conflict":
                message = self.loc.get("decision_manager_config_conflict")
            else:
                message = self.loc.get("decision_manager_save_failed").format(
                    error=self.registry.last_save_message or ""
                )
            QtWidgets.QMessageBox.critical(
                self,
                self.loc.get("decision_manager_title"),
                message,
            )
            return
        self._source_fingerprint = self.registry.get_config_fingerprint()
        self.accept()

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        answer = QtWidgets.QMessageBox.question(
            self,
            self.loc.get("decision_manager_discard_title"),
            self.loc.get("decision_manager_discard_confirm"),
            QtWidgets.QMessageBox.StandardButton.Yes
            | QtWidgets.QMessageBox.StandardButton.No,
            QtWidgets.QMessageBox.StandardButton.No,
        )
        return answer == QtWidgets.QMessageBox.StandardButton.Yes

    def reject(self) -> None:
        if self._confirm_discard():
            super().reject()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
