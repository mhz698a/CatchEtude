"""Editable in-memory model and validation for classification management."""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any


ALLOWED_PATH_PLACEHOLDERS = {
    "BASE_INTERNAL", "ONEDRIVE_DOCS", "ONEDRIVE_DOCTOS_FAMILIA",
    "IMAGES_FOLDER", "MUSIC_FOLDER", "OVERWORLD_FOLDER", "ACROBAT_FOLDER",
    "year", "year_prefix", "mtime_year", "mtime_month",
}


def validate_decision_configuration(decision: dict[str, Any]) -> None:
    """Validate editor-specific rules before the registry persists a decision."""
    decision_id = decision.get("id", "?")
    name = decision.get("name")
    if isinstance(name, dict):
        valid_names = [
            value for value in name.values()
            if isinstance(value, str) and value.strip()
        ]
        if not valid_names:
            raise ValueError(f"Decision {decision_id}: name cannot be empty")
    elif name is not None and (not isinstance(name, str) or not name.strip()):
        raise ValueError(f"Decision {decision_id}: name cannot be empty")
    elif not name and not decision.get("name_key"):
        raise ValueError(f"Decision {decision_id}: name cannot be empty")

    handler = decision.get("handler")
    if handler not in {"keep", "linear_docs", "move_to_subfolder"}:
        raise ValueError(f"Decision {decision_id}: unsupported handler")
    year_mode = decision.get("year_mode", "none")
    if year_mode not in {"none", "required"}:
        raise ValueError(f"Decision {decision_id}: invalid year mode")
    if handler == "linear_docs" and year_mode != "required":
        raise ValueError("Linear documentation requires year selection")

    icon = decision.get("icon", "")
    if icon and (
        not isinstance(icon, str)
        or Path(icon).name != icon
        or "/" in icon
        or "\\" in icon
    ):
        raise ValueError(f"Decision {decision_id}: icon must be an asset filename")

    if handler in {"move_to_subfolder", "linear_docs"}:
        base_path = decision.get("base_path")
        if not isinstance(base_path, str) or not base_path.strip():
            raise ValueError(f"Decision {decision_id}: base path is required")

    folder_source = decision.get("folder_source", "none")
    if folder_source not in {"none", "filesystem"}:
        raise ValueError(f"Decision {decision_id}: invalid folder source")
    contains = decision.get("folder_contains")
    fallback = decision.get("folder_fallback")
    if contains is not None and not isinstance(contains, str):
        raise ValueError(f"Decision {decision_id}: folder match must be text")
    if fallback is not None and not isinstance(fallback, str):
        raise ValueError(f"Decision {decision_id}: fallback path must be text")
    if fallback and not contains:
        raise ValueError(f"Decision {decision_id}: fallback requires a folder match")
    if contains and folder_source != "filesystem":
        raise ValueError(f"Decision {decision_id}: folder matching requires filesystem source")

    second_line = decision.get("behaviour_second_line")
    if second_line not in {
        None, "", "character_metadata", "last_file", "overworld_metadata"
    }:
        raise ValueError(f"Decision {decision_id}: unsupported second-line behavior")
    if second_line in {"character_metadata", "overworld_metadata"}:
        if year_mode != "required":
            raise ValueError(
                f"Decision {decision_id}: {second_line} requires year selection"
            )
        if handler != "move_to_subfolder" or folder_source != "filesystem":
            raise ValueError(
                f"Decision {decision_id}: {second_line} requires filesystem subfolders"
            )
    elif second_line == "last_file" and folder_source != "filesystem":
        raise ValueError(
            f"Decision {decision_id}: last_file requires filesystem subfolders"
        )
    if handler != "move_to_subfolder" and second_line not in {None, ""}:
        raise ValueError(
            f"Decision {decision_id}: this handler does not support a second-line behavior"
        )

    if folder_source == "none":
        if contains or fallback or second_line:
            raise ValueError(
                f"Decision {decision_id}: folder matching and secondary behavior require filesystem subfolders"
            )
        if any(
            decision.get(flag, False)
            for flag in ("allow_create", "allow_rename", "allow_delete")
        ):
            raise ValueError(
                f"Decision {decision_id}: subfolder permissions require filesystem subfolders"
            )

    templates = {
        key: decision.get(key)
        for key in ("base_path", "folder_contains", "folder_fallback")
    }
    if year_mode != "required" and any(
        token in str(template or "")
        for template in templates.values()
        for token in ("{year}", "{year_prefix}")
    ):
        raise ValueError(f"Decision {decision_id}: year variables require year selection")
    if handler != "linear_docs" and any(
        token in str(template or "")
        for template in templates.values()
        for token in ("{mtime_year}", "{mtime_month}")
    ):
        raise ValueError(
            "File modification date variables are only supported by linear documentation"
        )
    if handler == "linear_docs" and any(
        token in str(templates[key] or "")
        for key in ("folder_contains", "folder_fallback")
        for token in ("{mtime_year}", "{mtime_month}")
    ):
        raise ValueError(
            "File modification date variables are only supported in the base path"
        )
    if not decision.get("requires_internal", False) and "{BASE_INTERNAL}" in str(
        decision.get("base_path") or ""
    ):
        raise ValueError(
            f"Decision {decision_id}: a BASE_INTERNAL path requires the internal drive"
        )

    for key, template in templates.items():
        if not template:
            continue
        if not isinstance(template, str):
            raise ValueError(f"Decision {decision_id}: {key} must be text")
        tokens = re.findall(r"\{([^{}]+)\}", template)
        unknown = sorted(set(tokens) - ALLOWED_PATH_PLACEHOLDERS)
        if unknown:
            raise ValueError(
                f"Decision {decision_id}: unknown path variable(s) in {key}: "
                + ", ".join(unknown)
            )
        remainder = re.sub(r"\{[^{}]+\}", "", template)
        if "{" in remainder or "}" in remainder:
            raise ValueError(f"Decision {decision_id}: malformed placeholder in {key}")

    for flag in (
        "enabled", "requires_internal", "allow_create", "allow_rename", "allow_delete"
    ):
        if flag in decision and not isinstance(decision[flag], bool):
            raise ValueError(f"Decision {decision_id}: {flag} must be boolean")


class DecisionEditorModel:
    """Manage a private working copy of classification definitions."""

    EDITABLE_FIELDS = {
        "name", "icon", "year_mode", "base_path", "folder_source",
        "folder_contains", "folder_fallback", "behaviour_second_line",
        "requires_internal", "allow_create", "allow_rename", "allow_delete",
    }

    def __init__(self, decisions: list[dict[str, Any]]):
        if not isinstance(decisions, list):
            raise TypeError("decisions must be a list")
        self._decisions = sorted(
            copy.deepcopy(decisions),
            key=lambda item: (item.get("order", 0), item.get("id", 0)),
        )
        self._normalise_order()

    @property
    def decisions(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self._decisions)

    def snapshot(self) -> list[dict[str, Any]]:
        return self.decisions

    def get_decision(self, decision_id: int | None) -> dict[str, Any] | None:
        if decision_id is None:
            return None
        return next(
            (item for item in self._decisions if item.get("id") == decision_id),
            None,
        )

    def _index_of(self, decision_id: int) -> int:
        for index, item in enumerate(self._decisions):
            if item.get("id") == decision_id:
                return index
        raise KeyError(f"Unknown classification ID: {decision_id}")

    def _next_id(self) -> int:
        existing_ids = [
            item.get("id") for item in self._decisions
            if isinstance(item.get("id"), int)
            and not isinstance(item.get("id"), bool)
            and item.get("id") > 0
        ]
        return max(existing_ids, default=0) + 1

    def _normalise_order(self) -> None:
        for order, decision in enumerate(self._decisions, start=1):
            decision["order"] = order

    def add(self, name: str) -> int:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("A classification name is required")
        decision_id = self._next_id()
        self._decisions.append({
            "id": decision_id,
            "name": normalized_name,
            "icon": "",
            "enabled": True,
            "order": len(self._decisions) + 1,
            "handler": "move_to_subfolder",
            "year_mode": "none",
            "base_path": "{BASE_INTERNAL}",
            "folder_source": "filesystem",
            "requires_internal": True,
            "allow_create": True,
            "allow_rename": True,
            "allow_delete": True,
        })
        self._normalise_order()
        return decision_id

    def duplicate(self, decision_id: int, name: str) -> int:
        source_index = self._index_of(decision_id)
        source = self._decisions[source_index]
        if source.get("handler") == "keep":
            raise ValueError("The Keep classification cannot be duplicated")
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("A duplicated classification requires a name")
        duplicate = copy.deepcopy(source)
        new_id = self._next_id()
        duplicate["id"] = new_id
        duplicate["name"] = normalized_name
        duplicate.pop("name_key", None)
        duplicate["order"] = source_index + 2
        self._decisions.insert(source_index + 1, duplicate)
        self._normalise_order()
        return new_id

    def delete(self, decision_id: int) -> None:
        index = self._index_of(decision_id)
        if self._decisions[index].get("handler") == "keep":
            raise ValueError("The Keep classification cannot be deleted")
        del self._decisions[index]
        self._normalise_order()

    def update_fields(self, decision_id: int, fields: dict[str, Any]) -> bool:
        unknown = set(fields) - self.EDITABLE_FIELDS
        if unknown:
            raise ValueError("Unsupported editable field(s): " + ", ".join(sorted(unknown)))
        decision = self._decisions[self._index_of(decision_id)]
        changed = False
        for key, value in fields.items():
            if value is None or value == "":
                if key in decision:
                    del decision[key]
                    changed = True
                continue
            if decision.get(key) != value:
                decision[key] = copy.deepcopy(value)
                changed = True
        return changed

    def set_enabled(self, decision_id: int, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")
        self._decisions[self._index_of(decision_id)]["enabled"] = enabled

    def move(self, decision_id: int, offset: int) -> None:
        if offset not in (-1, 1):
            raise ValueError("offset must be -1 or 1")
        index = self._index_of(decision_id)
        target = index + offset
        if target < 0 or target >= len(self._decisions):
            return
        self._decisions[index], self._decisions[target] = (
            self._decisions[target], self._decisions[index]
        )
        self._normalise_order()
