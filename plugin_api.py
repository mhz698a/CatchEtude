"""
Plugin API constants, data structures, and manifest parsing logic for CatchEtude plugins.
"""

from enum import Enum
import re
import tomllib
from typing import Any, Dict, List, Optional, Tuple

PLUGIN_API_VERSION = 1

ALLOWED_CAPABILITIES = {
    "background_task",
    "event_listener",
    "tray_action",
    "ui_action",
    "settings",
    "parallel_service",
}

ALLOWED_EVENTS = {
    "app_started",
    "app_stopping",
    "file_detected",
    "move_finished",
    "settings_changed",
}

ID_REGEX = re.compile(r"^[a-z0-9][a-z0-9.-]{2,63}$")


class PluginState(str, Enum):
    DISCOVERED = "discovered"
    DISABLED = "disabled"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
    INVALID = "invalid"


class ServiceState(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


START_DELIMITER = "# /// catch-etude-plugin"
END_DELIMITER = "# /// end catch-etude-plugin"


def extract_manifest_toml(file_path: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts the raw TOML string from the embedded comment block within the first 200 lines of a file.
    Returns (toml_string, error_message).
    """
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = [f.readline() for _ in range(200)]
    except Exception as e:
        return None, f"Could not read file: {e}"

    start_idx = -1
    end_idx = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == START_DELIMITER:
            if start_idx != -1:
                return None, "Multiple start delimiters found in first 200 lines"
            start_idx = i
        elif stripped == END_DELIMITER:
            if start_idx != -1 and end_idx == -1:
                end_idx = i
                break

    if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
        return None, "Manifest delimiters not found within first 200 lines"

    toml_lines = []
    for line in lines[start_idx + 1:end_idx]:
        raw = line.strip()
        if raw.startswith("#"):
            # Strip leading comment char and up to 1 space
            comment_body = raw[1:]
            if comment_body.startswith(" "):
                comment_body = comment_body[1:]
            toml_lines.append(comment_body)
        else:
            toml_lines.append(raw)

    return "\n".join(toml_lines), None


def validate_manifest(manifest_dict: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validates the structure and constraints of a parsed plugin manifest dict.
    Returns (is_valid, error_message).
    """
    if "plugin" not in manifest_dict or not isinstance(manifest_dict["plugin"], dict):
        return False, "Missing or invalid [plugin] section"

    plugin_info = manifest_dict["plugin"]
    required_fields = ["id", "name", "version", "api_version", "capabilities", "events"]
    for field in required_fields:
        if field not in plugin_info:
            return False, f"Missing required field '{field}' in [plugin]"

    plugin_id = plugin_info["id"]
    if not isinstance(plugin_id, str) or not ID_REGEX.match(plugin_id):
        return False, f"Invalid plugin ID '{plugin_id}'. Must match ^[a-z0-9][a-z0-9.-]{{2,63}}$"

    if not isinstance(plugin_info["name"], str) or not plugin_info["name"].strip():
        return False, "Plugin 'name' must be a non-empty string"

    if not isinstance(plugin_info["version"], str) or not plugin_info["version"].strip():
        return False, "Plugin 'version' must be a non-empty string"

    if plugin_info["api_version"] != PLUGIN_API_VERSION:
        return False, f"Incompatible api_version {plugin_info['api_version']}. Supported: {PLUGIN_API_VERSION}"

    caps = plugin_info["capabilities"]
    if not isinstance(caps, list):
        return False, "'capabilities' must be a list of strings"
    for cap in caps:
        if cap not in ALLOWED_CAPABILITIES:
            return False, f"Unknown capability '{cap}'"
    caps_set = set(caps)

    events = plugin_info["events"]
    if not isinstance(events, list):
        return False, "'events' must be a list of strings"
    for ev in events:
        if ev not in ALLOWED_EVENTS:
            return False, f"Unknown event '{ev}'"

    # Validate tray_actions
    if "tray_actions" in manifest_dict:
        actions = manifest_dict["tray_actions"]
        if not isinstance(actions, list):
            return False, "'tray_actions' must be a list"
        if actions and "tray_action" not in caps_set:
            return False, "Declared 'tray_actions' without 'tray_action' capability"
        action_ids = set()
        for act in actions:
            if not isinstance(act, dict):
                return False, "Invalid item in 'tray_actions'"
            for f in ["id", "label", "command"]:
                if f not in act or not isinstance(act[f], str) or not act[f].strip():
                    return False, f"Tray action missing or empty field '{f}'"
            if act["id"] in action_ids:
                return False, f"Duplicate tray action id '{act['id']}'"
            action_ids.add(act["id"])

    # Validate action_buttons
    if "action_buttons" in manifest_dict:
        buttons = manifest_dict["action_buttons"]
        if not isinstance(buttons, list):
            return False, "'action_buttons' must be a list"
        if buttons and "ui_action" not in caps_set:
            return False, "Declared 'action_buttons' without 'ui_action' capability"
        btn_ids = set()
        for btn in buttons:
            if not isinstance(btn, dict):
                return False, "Invalid item in 'action_buttons'"
            for f in ["id", "label"]:
                if f not in btn or not isinstance(btn[f], str) or not btn[f].strip():
                    return False, f"Action button missing or empty field '{f}'"
            if btn["id"] in btn_ids:
                return False, f"Duplicate action button id '{btn['id']}'"
            btn_ids.add(btn["id"])

            if "file_extensions" in btn and not isinstance(btn["file_extensions"], list):
                return False, "'file_extensions' in action_buttons must be a list"

            if "menu_items" in btn:
                if not isinstance(btn["menu_items"], list):
                    return False, "'menu_items' in action_buttons must be a list"
                for item in btn["menu_items"]:
                    if not isinstance(item, dict):
                        return False, "Invalid menu item in action_buttons"
                    for f in ["label", "command"]:
                        if f not in item or not isinstance(item[f], str) or not item[f].strip():
                            return False, f"Menu item missing or empty field '{f}'"

    # Validate services
    if "services" in manifest_dict:
        services = manifest_dict["services"]
        if not isinstance(services, list):
            return False, "'services' must be a list"
        if services and "parallel_service" not in caps_set:
            return False, "Declared 'services' without 'parallel_service' capability"
        service_ids = set()
        for svc in services:
            if not isinstance(svc, dict):
                return False, "Invalid item in 'services'"
            svc_id = svc.get("id")
            if not isinstance(svc_id, str) or not ID_REGEX.match(svc_id):
                return False, f"Invalid service id '{svc_id}'"
            if svc_id in service_ids:
                return False, f"Duplicate service id '{svc_id}' within plugin"
            service_ids.add(svc_id)

            if not isinstance(svc.get("autostart"), bool):
                return False, f"Service '{svc_id}' autostart must be a boolean"

            if svc.get("restart_policy") != "never":
                return False, f"Service '{svc_id}' restart_policy must be 'never' in v1"

    # Validate settings_schema if present
    if "settings_schema" in manifest_dict:
        schema = manifest_dict["settings_schema"]
        if not isinstance(schema, dict):
            return False, "'settings_schema' must be a dict"
        if schema and "settings" not in caps_set:
            return False, "Declared 'settings_schema' without 'settings' capability"
        allowed_types = {"string", "integer", "number", "boolean"}
        for prop_name, prop_def in schema.items():
            if not isinstance(prop_def, dict):
                return False, f"Setting property '{prop_name}' definition must be a dict"
            prop_type = prop_def.get("type")
            if prop_type not in allowed_types:
                return False, f"Setting property '{prop_name}' has unsupported type '{prop_type}'"

    return True, None


def parse_and_validate_plugin_file(file_path: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Parses and validates a plugin file.
    Returns (manifest_dict, error_message).
    """
    toml_str, err = extract_manifest_toml(file_path)
    if err:
        return None, err

    try:
        manifest_dict = tomllib.loads(toml_str)
    except Exception as e:
        return None, f"TOML parsing error: {e}"

    is_valid, val_err = validate_manifest(manifest_dict)
    if not is_valid:
        return None, val_err

    return manifest_dict, None
