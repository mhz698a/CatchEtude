"""
Plugin Manager Dialog and Dynamic Plugin Settings Editor for CatchEtude.
"""

import os
import subprocess
from typing import Any, Dict, Optional

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import config
from localization import LocalizationManager
from plugin_api import PluginState, ServiceState
from plugin_manager import PluginManager


class PluginSettingsDialog(QDialog):
    """Dynamic settings dialog built from plugin's settings_schema."""

    def __init__(self, plugin_id: str, schema: Dict[str, Any], current_config: Dict[str, Any], loc: LocalizationManager, parent=None):
        super().__init__(parent)
        self.plugin_id = plugin_id
        self.schema = schema
        self.current_config = current_config
        self.loc = loc

        self.widgets: Dict[str, Any] = {}

        self.setWindowTitle(f"{loc.get('btn_plugin_settings')} - {plugin_id}")
        self.setMinimumWidth(380)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()

        for prop_name, prop_def in self.schema.items():
            prop_type = prop_def.get("type", "string")
            label_text = prop_def.get("title", prop_name)
            val = self.current_config.get(prop_name, prop_def.get("default"))

            if prop_type == "boolean":
                cb = QCheckBox()
                cb.setChecked(bool(val) if val is not None else False)
                form_layout.addRow(label_text, cb)
                self.widgets[prop_name] = ("boolean", cb)
            elif prop_type == "integer":
                sb = QSpinBox()
                sb.setRange(-2147483648, 2147483647)
                if val is not None:
                    sb.setValue(int(val))
                form_layout.addRow(label_text, sb)
                self.widgets[prop_name] = ("integer", sb)
            elif prop_type == "number":
                dsb = QDoubleSpinBox()
                dsb.setRange(-1e9, 1e9)
                if val is not None:
                    dsb.setValue(float(val))
                form_layout.addRow(label_text, dsb)
                self.widgets[prop_name] = ("number", dsb)
            else:  # string
                le = QLineEdit()
                if val is not None:
                    le.setText(str(val))
                form_layout.addRow(label_text, le)
                self.widgets[prop_name] = ("string", le)

        layout.addLayout(form_layout)

        btn_box = QHBoxLayout()
        btn_save = QPushButton(self.loc.get("btn_apply"))
        btn_save.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_save)
        btn_box.addWidget(btn_cancel)

        layout.addLayout(btn_box)

    def get_values(self) -> Dict[str, Any]:
        result = {}
        for prop_name, (prop_type, widget) in self.widgets.items():
            if prop_type == "boolean":
                result[prop_name] = widget.isChecked()
            elif prop_type == "integer":
                result[prop_name] = widget.value()
            elif prop_type == "number":
                result[prop_name] = widget.value()
            else:
                result[prop_name] = widget.text()
        return result


class PluginManagerDialog(QDialog):
    """Main Manager GUI for viewing, enabling, configuring and inspecting plugins."""

    def __init__(self, plugin_mgr: PluginManager, loc: LocalizationManager, parent=None):
        super().__init__(parent)
        self.plugin_mgr = plugin_mgr
        self.loc = loc

        self.setWindowTitle(loc.get("plugins_dialog_title"))
        self.resize(850, 480)

        self._init_ui()
        self._connect_signals()
        self.refresh_table()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Action Buttons Layout
        btn_layout = QHBoxLayout()

        self.btn_refresh = QPushButton(self.loc.get("btn_refresh_plugins"))
        self.btn_enable = QPushButton(self.loc.get("btn_enable_plugin"))
        self.btn_disable = QPushButton(self.loc.get("btn_disable_plugin"))
        self.btn_start = QPushButton(self.loc.get("btn_start_plugin"))
        self.btn_stop = QPushButton(self.loc.get("btn_stop_plugin"))
        self.btn_restart = QPushButton(self.loc.get("btn_restart_plugin"))
        self.btn_settings = QPushButton(self.loc.get("btn_plugin_settings"))
        self.btn_open_dir = QPushButton(self.loc.get("btn_open_plugins_dir"))
        self.btn_copy_diag = QPushButton(self.loc.get("btn_copy_diag"))

        btn_layout.addWidget(self.btn_refresh)
        btn_layout.addWidget(self.btn_enable)
        btn_layout.addWidget(self.btn_disable)
        btn_layout.addWidget(self.btn_start)
        btn_layout.addWidget(self.btn_stop)
        btn_layout.addWidget(self.btn_restart)
        btn_layout.addWidget(self.btn_settings)
        btn_layout.addWidget(self.btn_open_dir)
        btn_layout.addWidget(self.btn_copy_diag)

        layout.addLayout(btn_layout)

        # Table Widget
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            self.loc.get("col_plugin_file"),
            self.loc.get("col_plugin_id"),
            self.loc.get("col_plugin_name"),
            self.loc.get("col_plugin_ver"),
            self.loc.get("col_plugin_state"),
            self.loc.get("col_services_state"),
            self.loc.get("col_last_error"),
        ])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)

        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        layout.addWidget(self.table)

    def _connect_signals(self):
        self.btn_refresh.clicked.connect(self.on_refresh)
        self.btn_enable.clicked.connect(self.on_enable)
        self.btn_disable.clicked.connect(self.on_disable)
        self.btn_start.clicked.connect(self.on_start)
        self.btn_stop.clicked.connect(self.on_stop)
        self.btn_restart.clicked.connect(self.on_restart)
        self.btn_settings.clicked.connect(self.on_settings)
        self.btn_open_dir.clicked.connect(self.on_open_dir)
        self.btn_copy_diag.clicked.connect(self.on_copy_diag)

        self.table.itemSelectionChanged.connect(self._update_button_states)

        self.plugin_mgr.plugin_state_changed.connect(lambda p, s: self.refresh_table())
        self.plugin_mgr.service_state_changed.connect(lambda p, s, st: self.refresh_table())
        self.plugin_mgr.plugins_reloaded.connect(self.update_table_view)

    def refresh_table(self):
        self.plugin_mgr.discover()

    def update_table_view(self):
        selected_plugin_id = self._get_selected_plugin_id()
        discovered = list(self.plugin_mgr.registry.plugins.values())

        self.table.setRowCount(0)
        for row, plugin in enumerate(discovered):
            self.table.insertRow(row)

            file_item = QTableWidgetItem(plugin.file_name)
            id_item = QTableWidgetItem(plugin.plugin_id or "-")
            name_item = QTableWidgetItem(plugin.name)
            ver_item = QTableWidgetItem(plugin.version)

            # State text
            state_text = plugin.state.value
            proc = self.plugin_mgr.processes.get(plugin.plugin_id) if plugin.plugin_id else None
            if proc and proc.requires_restart:
                state_text += " (Restart required)"

            state_item = QTableWidgetItem(state_text)

            # Service state string
            svc_strs = []
            if plugin.plugin_id and proc:
                for s_id, s_proc in proc.services.items():
                    svc_strs.append(f"{s_id}:{s_proc.state.value}")
            services_item = QTableWidgetItem(", ".join(svc_strs) if svc_strs else "-")

            err_item = QTableWidgetItem(plugin.error_message or "-")

            file_item.setData(Qt.ItemDataRole.UserRole, plugin.plugin_id)

            self.table.setItem(row, 0, file_item)
            self.table.setItem(row, 1, id_item)
            self.table.setItem(row, 2, name_item)
            self.table.setItem(row, 3, ver_item)
            self.table.setItem(row, 4, state_item)
            self.table.setItem(row, 5, services_item)
            self.table.setItem(row, 6, err_item)

            if selected_plugin_id and plugin.plugin_id == selected_plugin_id:
                self.table.selectRow(row)

        self._update_button_states()

    def _get_selected_plugin_id(self) -> Optional[str]:
        selected_rows = self.table.selectedItems()
        if not selected_rows:
            return None
        row = selected_rows[0].row()
        return self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)

    def _update_button_states(self):
        plugin_id = self._get_selected_plugin_id()
        if not plugin_id:
            for btn in (self.btn_enable, self.btn_disable, self.btn_start, self.btn_stop, self.btn_restart, self.btn_settings, self.btn_copy_diag):
                btn.setEnabled(False)
            return

        proc = self.plugin_mgr.processes.get(plugin_id)
        if not proc:
            for btn in (self.btn_enable, self.btn_disable, self.btn_start, self.btn_stop, self.btn_restart, self.btn_settings):
                btn.setEnabled(False)
            self.btn_copy_diag.setEnabled(True)
            return

        plugin = proc.plugin

        self.btn_enable.setEnabled(not plugin.is_enabled and plugin.state != PluginState.INVALID)
        self.btn_disable.setEnabled(plugin.is_enabled)

        self.btn_start.setEnabled(plugin.is_enabled and plugin.state in (PluginState.STOPPED, PluginState.DISCOVERED, PluginState.DISABLED))
        self.btn_stop.setEnabled(plugin.state in (PluginState.RUNNING, PluginState.STARTING))
        self.btn_restart.setEnabled(plugin.is_enabled)
        self.btn_settings.setEnabled(bool(plugin.settings_schema))
        self.btn_copy_diag.setEnabled(True)

    def on_refresh(self):
        self.refresh_table()

    def on_enable(self):
        plugin_id = self._get_selected_plugin_id()
        if not plugin_id:
            return

        proc = self.plugin_mgr.processes.get(plugin_id)
        if not proc:
            return

        # Trust confirmation dialog (RF-02 item 4)
        confirm_text = self.loc.get("msg_trust_confirm").format(file=proc.plugin.file_name)
        reply = QMessageBox.warning(
            self,
            self.loc.get("msg_trust_title"),
            confirm_text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.plugin_mgr.enable_plugin(plugin_id)
            self.refresh_table()

    def on_disable(self):
        plugin_id = self._get_selected_plugin_id()
        if plugin_id:
            self.plugin_mgr.disable_plugin(plugin_id)
            self.refresh_table()

    def on_start(self):
        plugin_id = self._get_selected_plugin_id()
        if plugin_id:
            self.plugin_mgr.start_plugin(plugin_id)
            self.refresh_table()

    def on_stop(self):
        plugin_id = self._get_selected_plugin_id()
        if plugin_id:
            self.plugin_mgr.stop_plugin(plugin_id)
            self.refresh_table()

    def on_restart(self):
        plugin_id = self._get_selected_plugin_id()
        if plugin_id:
            self.plugin_mgr.restart_plugin(plugin_id)
            self.refresh_table()

    def on_settings(self):
        plugin_id = self._get_selected_plugin_id()
        if not plugin_id:
            return

        proc = self.plugin_mgr.processes.get(plugin_id)
        if not proc or not proc.plugin.settings_schema:
            return

        current_cfg = self.plugin_mgr.registry.get_plugin_config(plugin_id)
        dlg = PluginSettingsDialog(plugin_id, proc.plugin.settings_schema, current_cfg, self.loc, self)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_cfg = dlg.get_values()
            self.plugin_mgr.update_plugin_config(plugin_id, new_cfg)

    def on_open_dir(self):
        os.startfile(config.PLUGINS_DIR)

    def on_copy_diag(self):
        plugin_id = self._get_selected_plugin_id()
        if not plugin_id:
            return

        proc = self.plugin_mgr.processes.get(plugin_id)
        if not proc:
            return

        plugin = proc.plugin
        diag_lines = [
            f"--- CatchEtude Plugin Diagnostic ---",
            f"ID: {plugin.plugin_id}",
            f"Name: {plugin.name}",
            f"Version: {plugin.version}",
            f"API Version: {plugin.api_version}",
            f"File: {plugin.file_name}",
            f"Enabled: {plugin.is_enabled}",
            f"State: {plugin.state.value}",
            f"Last Error: {plugin.error_message or 'None'}",
            f"Services:",
        ]

        for s_id, s_proc in proc.services.items():
            diag_lines.append(f"  - {s_id}: state={s_proc.state.value}, error={s_proc.error_message or 'None'}")

        diag_lines.append(f"Manifest:")
        diag_lines.append(str(plugin.manifest))

        diag_text = "\n".join(diag_lines)
        QApplication.clipboard().setText(diag_text)
        QMessageBox.information(self, self.loc.get("btn_copy_diag"), "Diagnostic information copied to clipboard.")
