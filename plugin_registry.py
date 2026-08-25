"""
Plugin Registry module for CatchEtude.
Handles scanning, manifest extraction, state persistence, and configuration storage for plugins.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import config
from plugin_api import (
    PluginState,
    ServiceState,
    parse_and_validate_plugin_file,
)

logger = logging.getLogger(__name__)


def _atomic_write_json(file_path: Path, data: Any) -> None:
    """Writes data to a temporary file and atomically replaces the target file."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp_path.replace(file_path)


class DiscoveredPlugin:
    """Represents a discovered plugin file and its metadata."""

    def __init__(self, file_path: Path):
        self.file_path = file_path.resolve()
        self.file_name = file_path.name
        self.file_mtime: float = file_path.stat().st_mtime if file_path.exists() else 0.0
        self.manifest: Optional[Dict[str, Any]] = None
        self.plugin_id: Optional[str] = None
        self.name: str = file_path.stem
        self.version: str = "0.0.0"
        self.api_version: int = 1
        self.capabilities: List[str] = []
        self.events: List[str] = []
        self.tray_actions: List[Dict[str, str]] = []
        self.services: List[Dict[str, Any]] = []
        self.settings_schema: Dict[str, Any] = {}

        self.state: PluginState = PluginState.DISCOVERED
        self.is_enabled: bool = False
        self.error_message: Optional[str] = None
        self.last_change: str = ""
        self.service_states: Dict[str, ServiceState] = {}

    def parse(self) -> bool:
        """Parses and validates the plugin file. Returns True if valid."""
        manifest, err = parse_and_validate_plugin_file(str(self.file_path))
        if err or manifest is None:
            self.state = PluginState.INVALID
            self.error_message = err or "Unknown validation error"
            return False

        self.manifest = manifest
        info = manifest["plugin"]
        self.plugin_id = info["id"]
        self.name = info["name"]
        self.version = info["version"]
        self.api_version = info["api_version"]
        self.capabilities = info.get("capabilities", [])
        self.events = info.get("events", [])
        self.tray_actions = manifest.get("tray_actions", [])
        self.services = manifest.get("services", [])
        self.settings_schema = manifest.get("settings_schema", {})

        for svc in self.services:
            self.service_states[svc["id"]] = ServiceState.STOPPED

        self.state = PluginState.DISCOVERED
        self.error_message = None
        return True


class PluginRegistry:
    """
    Manages discovery of plugin files in PLUGINS_DIR and persistent plugin state/config in APPDATA.
    """

    def __init__(
        self,
        plugins_dir: Optional[Path] = None,
        state_path: Optional[Path] = None,
        config_dir: Optional[Path] = None,
    ):
        self.plugins_dir = plugins_dir if plugins_dir is not None else config.PLUGINS_DIR
        self.state_path = state_path if state_path is not None else config.PLUGIN_STATE_PATH
        self.config_dir = config_dir if config_dir is not None else config.PLUGIN_CONFIG_DIR

        self.plugins: Dict[Path, DiscoveredPlugin] = {}  # Key: absolute Path
        self.plugins_by_id: Dict[str, DiscoveredPlugin] = {}  # Key: plugin_id

    def load_states(self) -> Dict[str, Any]:
        """Loads persistent plugin states from plugins-state.json."""
        if not self.state_path.exists():
            return {}
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error(f"Failed to load plugin state file {self.state_path}: {e}")
            return {}

    def save_states(self) -> None:
        """Saves current enable states to plugins-state.json."""
        state_data = {}
        # Keep existing state data for orphan entries if needed
        existing = self.load_states()
        state_data.update(existing)

        for plugin in self.plugins.values():
            if plugin.plugin_id:
                state_data[plugin.plugin_id] = {
                    "enabled": plugin.is_enabled,
                    "file_name": plugin.file_name,
                }
        try:
            _atomic_write_json(self.state_path, state_data)
        except Exception as e:
            logger.error(f"Failed to save plugin states: {e}")

    def get_plugin_config(self, plugin_id: str) -> Dict[str, Any]:
        """Loads configuration for a given plugin ID from plugins-config/<id>.json."""
        cfg_path = self.config_dir / f"{plugin_id}.json"
        if not cfg_path.exists():
            return {}
        try:
            with open(cfg_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.error(f"Failed to load config for plugin '{plugin_id}': {e}")
            return {}

    def save_plugin_config(self, plugin_id: str, config_data: Dict[str, Any]) -> bool:
        """Saves configuration for a given plugin ID atomically."""
        cfg_path = self.config_dir / f"{plugin_id}.json"
        try:
            _atomic_write_json(cfg_path, config_data)
            return True
        except Exception as e:
            logger.error(f"Failed to save config for plugin '{plugin_id}': {e}")
            return False

    def discover(self) -> List[DiscoveredPlugin]:
        """
        Scans PLUGINS_DIR for regular .py and .pyw files, parses manifests, checks duplicates,
        and updates active plugins list.
        """
        self.plugins.clear()
        self.plugins_by_id.clear()

        if not self.plugins_dir.exists():
            self.plugins_dir.mkdir(parents=True, exist_ok=True)
            return []

        saved_states = self.load_states()

        discovered_list: List[DiscoveredPlugin] = []
        seen_ids: Dict[str, Path] = {}

        # Iterate directly in PLUGINS_DIR for regular files
        for entry in self.plugins_dir.iterdir():
            # Must be regular file and have .py or .pyw extension, no symlinks
            if entry.is_dir() or entry.is_symlink() or not entry.is_file():
                continue
            if entry.suffix.lower() not in (".py", ".pyw"):
                continue

            entry_mtime = entry.stat().st_mtime if entry.exists() else 0.0
            existing_by_path = self.plugins.get(entry.resolve())

            # If plugin is already loaded and active, check if mtime changed
            plugin = DiscoveredPlugin(entry)
            is_valid = plugin.parse()

            if is_valid and plugin.plugin_id:
                if plugin.plugin_id in seen_ids:
                    # Duplicate ID! Mark invalid
                    first_file = seen_ids[plugin.plugin_id]
                    plugin.state = PluginState.INVALID
                    plugin.error_message = f"Duplicate plugin ID '{plugin.plugin_id}' (first seen in '{first_file.name}')"
                else:
                    seen_ids[plugin.plugin_id] = entry
                    # Load saved enabled state
                    saved = saved_states.get(plugin.plugin_id, {})
                    plugin.is_enabled = saved.get("enabled", False)
                    if not plugin.is_enabled:
                        plugin.state = PluginState.DISABLED
                    self.plugins_by_id[plugin.plugin_id] = plugin

            self.plugins[entry.resolve()] = plugin
            discovered_list.append(plugin)

        return discovered_list

    def set_enabled(self, plugin_id: str, enabled: bool) -> bool:
        """Enables or disables a plugin by ID and persists state."""
        plugin = self.plugins_by_id.get(plugin_id)
        if not plugin or plugin.state == PluginState.INVALID:
            return False

        plugin.is_enabled = enabled
        if not enabled and plugin.state in (PluginState.RUNNING, PluginState.STARTING, PluginState.DISCOVERED):
            plugin.state = PluginState.DISABLED
        elif enabled and plugin.state == PluginState.DISABLED:
            plugin.state = PluginState.DISCOVERED

        self.save_states()
        return True
