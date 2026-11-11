"""Visual manager for CatchEtude classification definitions (stage 1)."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from PyQt6 import QtCore, QtGui, QtWidgets

import config
from classification_registry import ClassificationRegistry
from decision_editor_model import DecisionEditorModel


class DecisionManagerDialog(QtWidgets.QDialog):
    """Manage classification order, visibility, creation and deletion."""

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

        self.setWindowTitle(self.loc.get("decision_manager_title"))
        self.setWindowIcon(QtGui.QIcon(config.ICON_PATH))
        self.setMinimumSize(760, 500)
        self.resize(900, 570)
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
        self.list_widget.setMinimumWidth(330)
        self.list_widget.currentItemChanged.connect(self._on_current_item_changed)
        self.list_widget.itemChanged.connect(self._on_item_changed)
        left.addWidget(self.list_widget, 1)

        primary_buttons = QtWidgets.QHBoxLayout()
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
        primary_buttons.addWidget(self.btn_new)
        primary_buttons.addWidget(self.btn_duplicate)
        primary_buttons.addWidget(self.btn_remove)
        left.addLayout(primary_buttons)

        order_buttons = QtWidgets.QHBoxLayout()
        self.btn_up = QtWidgets.QPushButton(self.loc.get("decision_manager_up"))
        self.btn_down = QtWidgets.QPushButton(self.loc.get("decision_manager_down"))
        self.btn_up.clicked.connect(lambda: self._move_decision(-1))
        self.btn_down.clicked.connect(lambda: self._move_decision(1))
        order_buttons.addWidget(self.btn_up)
        order_buttons.addWidget(self.btn_down)
        order_buttons.addStretch(1)
        left.addLayout(order_buttons)

        content.addLayout(left, 3)

        right = QtWidgets.QVBoxLayout()
        details_box = QtWidgets.QGroupBox(
            self.loc.get("decision_manager_details")
        )
        details_form = QtWidgets.QFormLayout(details_box)

        self.detail_name = QtWidgets.QLabel("—")
        self.detail_id = QtWidgets.QLabel("—")
        self.detail_handler = QtWidgets.QLabel("—")
        self.detail_order = QtWidgets.QLabel("—")
        self.detail_state = QtWidgets.QLabel("—")
        for label in (
            self.detail_name,
            self.detail_id,
            self.detail_handler,
            self.detail_order,
            self.detail_state,
        ):
            label.setTextInteractionFlags(
                QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
            )
            label.setWordWrap(True)

        details_form.addRow(
            self.loc.get("decision_manager_name"), self.detail_name
        )
        details_form.addRow("ID", self.detail_id)
        details_form.addRow(
            self.loc.get("decision_manager_handler"), self.detail_handler
        )
        details_form.addRow(
            self.loc.get("decision_manager_order"), self.detail_order
        )
        details_form.addRow(
            self.loc.get("decision_manager_status"), self.detail_state
        )
        right.addWidget(details_box)

        note = QtWidgets.QLabel(
            self.loc.get("decision_manager_stage_two_notice")
        )
        note.setWordWrap(True)
        note.setStyleSheet(
            "QLabel { padding: 10px; background: palette(alternate-base); "
            "border-radius: 5px; color: palette(text); }"
        )
        right.addWidget(note)
        right.addStretch(1)
        content.addLayout(right, 2)
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

    def _decision_icon(self, decision: dict[str, Any]) -> QtGui.QIcon:
        icon_name = str(decision.get("icon") or "").strip()
        if icon_name:
            icon_path = Path(config.APP_DIR) / "assets" / icon_name
            if icon_path.is_file():
                return QtGui.QIcon(str(icon_path))
        fallback = QtGui.QIcon.fromTheme("folder")
        return fallback if not fallback.isNull() else QtGui.QIcon(config.ICON_PATH)

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
        value = item.data(QtCore.Qt.ItemDataRole.UserRole)
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _refresh_list(self, selected_id: int | None = None) -> None:
        if selected_id is None:
            selected_id = self._current_id()

        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        selected_row = -1

        for row, decision in enumerate(self.model.decisions):
            name = self.registry.get_decision_name(
                decision, self.loc.current_lang(), self.loc
            )
            handler = self._handler_label(decision.get("handler", ""))
            item = QtWidgets.QListWidgetItem(
                self._decision_icon(decision),
                f"{name}\nID {decision['id']} · {handler}",
            )
            item.setData(
                QtCore.Qt.ItemDataRole.UserRole, decision["id"]
            )
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

    def _refresh_details(self) -> None:
        decision = self.model.get_decision(self._current_id())
        if decision is None:
            values = ("—", "—", "—", "—", "—")
        else:
            values = (
                self.registry.get_decision_name(
                    decision, self.loc.current_lang(), self.loc
                ),
                str(decision["id"]),
                self._handler_label(decision.get("handler", "")),
                str(decision.get("order", 0)),
                self.loc.get(
                    "decision_manager_enabled"
                    if decision.get("enabled", True)
                    else "decision_manager_disabled"
                ),
            )
        for widget, value in zip(
            (
                self.detail_name,
                self.detail_id,
                self.detail_handler,
                self.detail_order,
                self.detail_state,
            ),
            values,
        ):
            widget.setText(value)

    def _refresh_controls(self) -> None:
        decision_id = self._current_id()
        decision = self.model.get_decision(decision_id)
        index = next(
            (
                i for i, item in enumerate(self.model.decisions)
                if item.get("id") == decision_id
            ),
            -1,
        )
        has_selection = decision is not None
        self.btn_duplicate.setEnabled(
            has_selection and decision.get("handler") != "keep"
        )
        self.btn_remove.setEnabled(
            has_selection and decision.get("handler") != "keep"
        )
        self.btn_up.setEnabled(has_selection and index > 0)
        self.btn_down.setEnabled(
            has_selection and index >= 0
            and index < len(self.model.decisions) - 1
        )
        if decision and decision.get("handler") == "keep":
            self.btn_remove.setToolTip(
                self.loc.get("decision_manager_keep_protected")
            )
            self.btn_duplicate.setToolTip(
                self.loc.get("decision_manager_keep_protected")
            )
        else:
            self.btn_remove.setToolTip("")
            self.btn_duplicate.setToolTip("")

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.btn_save.setEnabled(True)
        self.status_label.setText(
            self.loc.get("decision_manager_changes_pending")
        )

    def _on_current_item_changed(self, current, previous) -> None:
        self._refresh_details()
        self._refresh_controls()

    def _on_item_changed(self, item: QtWidgets.QListWidgetItem) -> None:
        decision_id = item.data(QtCore.Qt.ItemDataRole.UserRole)
        enabled = item.checkState() == QtCore.Qt.CheckState.Checked
        try:
            self.model.set_enabled(int(decision_id), enabled)
        except (KeyError, TypeError, ValueError):
            return
        self._mark_dirty()
        self._refresh_details()

    def _add_decision(self) -> None:
        decision_id = self.model.add(
            self.loc.get("decision_manager_new_name")
        )
        self._refresh_list(decision_id)
        self._mark_dirty()

    def _duplicate_decision(self) -> None:
        decision_id = self._current_id()
        decision = self.model.get_decision(decision_id)
        if decision is None or decision.get("handler") == "keep":
            return
        current_name = self.registry.get_decision_name(
            decision, self.loc.current_lang(), self.loc
        )
        new_name = (
            f"{self.loc.get('decision_manager_copy_prefix')} {current_name}"
        )
        try:
            duplicate_id = self.model.duplicate(decision_id, new_name)
        except (KeyError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self,
                self.loc.get("decision_manager_title"),
                str(exc),
            )
            return
        self._refresh_list(duplicate_id)
        self._mark_dirty()

    def _remove_decision(self) -> None:
        decision_id = self._current_id()
        decision = self.model.get_decision(decision_id)
        if decision is None or decision.get("handler") == "keep":
            return
        name = self.registry.get_decision_name(
            decision, self.loc.current_lang(), self.loc
        )
        message = self.loc.get(
            "decision_manager_confirm_delete"
        ).format(name=name)
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
                self,
                self.loc.get("decision_manager_title"),
                str(exc),
            )
            return
        self._refresh_list()
        self._mark_dirty()

    def _move_decision(self, offset: int) -> None:
        decision_id = self._current_id()
        if decision_id is None:
            return
        try:
            self.model.move(decision_id, offset)
        except (KeyError, ValueError):
            return
        self._refresh_list(decision_id)
        self._mark_dirty()

    def _save(self) -> None:
        if not self._dirty:
            self.accept()
            return

        candidate = self.model.snapshot()
        try:
            ClassificationRegistry.validate_decisions(candidate)
        except (TypeError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self,
                self.loc.get("decision_manager_title"),
                str(exc),
            )
            return

        previous = copy.deepcopy(self.registry.decisions)
        self.registry.decisions = candidate
        if not self.registry.save_config():
            self.registry.decisions = previous
            QtWidgets.QMessageBox.critical(
                self,
                self.loc.get("decision_manager_title"),
                self.loc.get("decision_manager_save_failed"),
            )
            return
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
