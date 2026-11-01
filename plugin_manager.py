"""
PluginManager facade for CatchEtude.
Coordinates plugin discovery, lifecycle management, event dispatching, and configuration.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from PyQt6.QtCore import QObject, pyqtSignal

import config
from plugin_api import PluginState, ServiceState
from plugin_host import PluginProcess
from plugin_registry import DiscoveredPlugin, PluginRegistry

logger = logging.getLogger(__name__)


class PluginManager(QObject):
    """Facade for managing all application plugins."""

    plugin_state_changed = pyqtSignal(str, str)  # plugin_id, new_state
    service_state_changed = pyqtSignal(str, str, str)  # plugin_id, service_id, new_state
    plugins_reloaded = pyqtSignal()

    def __init__(self, plugins_dir: Optional[Path] = None, parent=None):
        super().__init__(parent)
        if plugins_dir is None:
            plugins_dir = config.PLUGINS_DIR
        self.registry = PluginRegistry(plugins_dir=plugins_dir)
        self.processes: Dict[str, PluginProcess] = {}  # plugin_id -> PluginProcess

    def _create_process(self, plugin: DiscoveredPlugin) -> PluginProcess:
        """Creates a process host and wires its lifecycle signals."""
        proc = PluginProcess(plugin, self.registry, self)
        proc.state_changed.connect(
            lambda state, p_id=plugin.plugin_id: self.plugin_state_changed.emit(p_id, state)
        )
        for svc_id, svc_proc in proc.services.items():
            svc_proc.state_changed.connect(
                lambda state, p_id=plugin.plugin_id, s_id=svc_id: self.service_state_changed.emit(p_id, s_id, state)
            )
        return proc

    def discover(self) -> List[DiscoveredPlugin]:
        """Scans plugin directory while preserving the runtime instances used by processes."""
        previous_sources = {
            plugin_id: (proc.plugin.file_path, proc.plugin.file_mtime)
            for plugin_id, proc in self.processes.items()
        }
        discovered = self.registry.discover()

        for plugin in discovered:
            if not plugin.plugin_id or plugin.state == PluginState.INVALID:
                continue

            existing_proc = self.processes.get(plugin.plugin_id)
            if existing_proc is None:
                self.processes[plugin.plugin_id] = self._create_process(plugin)
                continue

            # PluginRegistry refreshes metadata in-place, so PluginProcess keeps a
            # valid reference to the same object. Compare against the pre-scan mtime
            # (not the already-refreshed value) to detect source updates.
            previous_source = previous_sources.get(plugin.plugin_id)
            current_source = (plugin.file_path, plugin.file_mtime)
            if previous_source is not None and previous_source != current_source:
                existing_proc.requires_restart = True

        self.plugins_reloaded.emit()
        return discovered

    def start_enabled_plugins(self) -> None:
        """Starts all discovered plugins that are enabled."""
        self.discover()
        for plugin_id, proc in self.processes.items():
            if proc.plugin.is_enabled and proc.plugin.state in (PluginState.DISABLED, PluginState.DISCOVERED, PluginState.STOPPED):
                proc.start()

    def start_plugin(self, plugin_id: str) -> bool:
        """Starts a specific enabled plugin without restarting the application."""
        proc = self.processes.get(plugin_id)
        if proc is None:
            self.discover()
            proc = self.processes.get(plugin_id)
        if proc is None or not proc.plugin.is_enabled:
            return False

        if proc.plugin.state in (PluginState.RUNNING, PluginState.STARTING):
            return True

        if proc.requires_restart:
            proc = self._replace_process(plugin_id, proc)

        proc.start()
        return True

    def _replace_process(self, plugin_id: str, old_proc: PluginProcess) -> PluginProcess:
        """Rebuilds the host so changed plugin code and service declarations are loaded."""
        plugin = old_proc.plugin
        new_proc = self._create_process(plugin)
        new_proc.requires_restart = False
        self.processes[plugin_id] = new_proc
        old_proc.deleteLater()
        return new_proc

    def stop_plugin(self, plugin_id: str) -> bool:
        """Stops a specific plugin."""
        proc = self.processes.get(plugin_id)
        if not proc:
            return False
        proc.stop()
        return True

    def restart_plugin(self, plugin_id: str) -> bool:
        """Restarts a plugin process and reloads changed code/services when needed."""
        proc = self.processes.get(plugin_id)
        if proc is None:
            return False

        was_enabled = proc.plugin.is_enabled
        proc.stop()
        if proc.requires_restart:
            proc = self._replace_process(plugin_id, proc)

        if was_enabled:
            proc.requires_restart = False
            proc.start()
            return True
        return False

    def enable_plugin(self, plugin_id: str) -> bool:
        """Enables a plugin and starts it immediately."""
        if plugin_id not in self.registry.plugins_by_id:
            self.discover()
        if not self.registry.set_enabled(plugin_id, True):
            return False
        return self.start_plugin(plugin_id)

    def disable_plugin(self, plugin_id: str) -> bool:
        """Disables a plugin and stops its process immediately."""
        if not self.registry.set_enabled(plugin_id, False):
            return False

        proc = self.processes.get(plugin_id)
        if proc is not None:
            proc.stop()
            if proc.plugin.state != PluginState.DISABLED:
                proc.set_state(PluginState.DISABLED)
        return True

    def publish_event(self, event_name: str, data: Dict[str, Any]) -> None:
        """Publishes an event to all running plugins that declared it."""
        for proc in self.processes.values():
            if proc.plugin.state == PluginState.RUNNING:
                proc.send_event(event_name, data)

    def invoke_command(self, plugin_id: str, command: str, args: Dict[str, Any] = None) -> bool:
        """Invokes a tray action command on a specific plugin."""
        proc = self.processes.get(plugin_id)
        if not proc or proc.plugin.state != PluginState.RUNNING:
            return False
        proc.send_command(command, args)
        return True

    def get_tray_actions(self) -> List[Dict[str, Any]]:
        """Returns list of tray action dicts with plugin_id for running plugins."""
        actions = []
        for plugin_id, proc in self.processes.items():
            if proc.plugin.state == PluginState.RUNNING:
                for act in proc.plugin.tray_actions:
                    item = dict(act)
                    item["plugin_id"] = plugin_id
                    actions.append(item)
        return actions

    def get_ui_action_buttons(self) -> List[Dict[str, Any]]:
        """Returns list of UI action button dicts with plugin_id for running plugins."""
        buttons = []
        for plugin_id, proc in self.processes.items():
            if proc.plugin.state == PluginState.RUNNING:
                for btn in proc.plugin.action_buttons:
                    item = dict(btn)
                    item["plugin_id"] = plugin_id
                    buttons.append(item)
        return buttons

    def update_plugin_config(self, plugin_id: str, new_config: Dict[str, Any]) -> bool:
        """Updates plugin configuration and notifies active process."""
        if self.registry.save_plugin_config(plugin_id, new_config):
            proc = self.processes.get(plugin_id)
            if proc:
                proc.send_settings_changed(new_config)
            return True
        return False

    def shutdown(self) -> None:
        """Gracefully stops all plugins and services during app shutdown (up to 5s timeout)."""
        logger.info("Publishing app_stopping event to plugins...")
        self.publish_event("app_stopping", {})

        for plugin_id, proc in self.processes.items():
            try:
                proc.stop(reason="App shutting down")
            except Exception as e:
                logger.error(f"Error stopping plugin '{plugin_id}': {e}")
