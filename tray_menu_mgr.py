"""
Tray menu manager for CatchEtude.
Gestor del menú de la bandeja del sistema para CatchEtude.
"""

import sys
import logging
from pathlib import Path
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon
from PyQt6.QtGui import QIcon, QAction

import config


class TrayMenuManager:
    """
    Manages the system tray icon, context menu, standard actions,
    and dynamic plugin tray actions for CatchEtude.
    """

    def __init__(self, main_window):
        self.main_window = main_window
        self.tray = None
        self.tray_menu = None
        self.toggle_show_hide_action = None

    def update_show_hide_action(self):
        """Updates the label of the show/hide action according to main window visibility."""
        if self.toggle_show_hide_action is not None:
            if self.main_window.isVisible():
                self.toggle_show_hide_action.setText(self.main_window.loc.get("tray_hide"))
            else:
                self.toggle_show_hide_action.setText(self.main_window.loc.get("tray_show"))

    def build_tray(self):
        """Builds or rebuilds the system tray icon and context menu."""
        mw = self.main_window
        loc = mw.loc

        icon = QIcon.fromTheme("folder-downloads")
        if icon.isNull():
            icon = QIcon(config.ICON_PATH)

        if self.tray is None:
            self.tray = QSystemTrayIcon(icon, mw)
            self.tray.setToolTip(config.APP_NAME)

        self.tray_menu = QMenu(mw)

        toggle_label = loc.get("tray_hide") if mw.isVisible() else loc.get("tray_show")
        self.toggle_show_hide_action = QAction(toggle_label, mw)
        self.toggle_show_hide_action.triggered.connect(mw._toggle_show_hide)
        self.tray_menu.addAction(self.toggle_show_hide_action)

        rescan_action = QAction(loc.get("tray_rescan"), mw)
        rescan_action.triggered.connect(mw._rescan_downloads)
        self.tray_menu.addAction(rescan_action)

        order_pending_action = QAction(loc.get("tray_order_pending"), mw)
        order_pending_action.triggered.connect(mw._on_order_pending_clicked)
        self.tray_menu.addAction(order_pending_action)

        run_pendings_action = QAction(loc.get("tray_run_pendings"), mw)
        run_pendings_action.triggered.connect(mw._run_pendings)
        self.tray_menu.addAction(run_pendings_action)

        open_last_action = QAction(loc.get("tray_open_last"), mw)
        last_move = mw.background_move_mgr._history.get_last_move()
        open_last_action.setEnabled(bool(last_move))
        open_last_action.triggered.connect(mw._open_last_chosen)
        self.tray_menu.addAction(open_last_action)

        open_recent_file_action = QAction(loc.get("last_file_open"), mw)
        open_recent_file_action.setEnabled(bool(last_move))
        open_recent_file_action.triggered.connect(mw._open_recent_file)
        self.tray_menu.addAction(open_recent_file_action)

        undo_action = QAction(loc.get("tray_undo"), mw)
        undo_action.triggered.connect(mw._on_tray_undo_clicked)
        self.tray_menu.addAction(undo_action)

        center_action = QAction(loc.get("tray_center"), mw)
        center_action.triggered.connect(mw._bring_and_center)
        self.tray_menu.addAction(center_action)

        logs_action = QAction(loc.get("tray_logs"), mw)
        logs_action.triggered.connect(mw._show_logs)
        self.tray_menu.addAction(logs_action)

        plugins_action = QAction(loc.get("tray_plugins"), mw)
        plugins_action.triggered.connect(mw._show_plugin_manager)
        self.tray_menu.addAction(plugins_action)

        self._build_or_update_plugins_submenu()

        appdta_folder_action = QAction("Open Appdata Folder", mw)
        appdta_folder_action.triggered.connect(mw._open_appdta_folder)
        self.tray_menu.addAction(appdta_folder_action)

        settings_action = QAction(loc.get("tray_settings"), mw)
        settings_action.triggered.connect(mw._open_settings_dialog)
        self.tray_menu.addAction(settings_action)

        restart_action = QAction(loc.get("tray_restart"), mw)
        restart_action.triggered.connect(mw._restart_service)
        self.tray_menu.addAction(restart_action)

        quit_action = QAction(loc.get("tray_exit"), mw)
        quit_action.triggered.connect(mw._on_exit_clicked)
        self.tray_menu.addAction(quit_action)

        self.tray.setContextMenu(self.tray_menu)
        self.tray.show()

    def _build_or_update_plugins_submenu(self):
        plugin_actions = self._get_plugin_tray_actions()
        if not plugin_actions:
            return

        mw = self.main_window
        grouped_menus = {}
        for act_def in plugin_actions:
            pid = act_def.get("plugin_id")
            label = act_def.get("label", "Action")
            command = act_def.get("command", "")
            group = act_def.get("group")

            act = QAction(label, mw)
            act.triggered.connect(lambda checked, p=pid, c=command: self._on_plugin_tray_action(p, c))

            if group:
                if group not in grouped_menus:
                    grouped_menus[group] = QMenu(group, mw)
                    self.tray_menu.addMenu(grouped_menus[group])
                grouped_menus[group].addAction(act)
            else:
                self.tray_menu.addAction(act)

    def _get_plugin_tray_actions(self):
        try:
            plugin_mgr = getattr(sys.modules.get("__main__"), "plugin_mgr", None)
            if plugin_mgr:
                return plugin_mgr.get_tray_actions()
        except Exception:
            logging.exception("Failed to load plugin tray actions")
        return []

    def _on_plugin_tray_action(self, plugin_id: str, command: str):
        try:
            plugin_mgr = getattr(sys.modules.get("__main__"), "plugin_mgr", None)
            if plugin_mgr:
                plugin_mgr.invoke_command(plugin_id, command)
        except Exception:
            logging.exception(f"Failed to execute plugin tray action '{command}' for '{plugin_id}'")
