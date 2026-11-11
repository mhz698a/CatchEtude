"""Editable in-memory model for classification management.

The model deliberately has no Qt dependency. It prepares a candidate list;
persistence is handled by ClassificationRegistry only after validation.
"""
from __future__ import annotations

import copy
from typing import Any


class DecisionEditorModel:
    """Manage a private working copy of classification definitions."""

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
        """Return a defensive copy of the current working decisions."""
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
            item.get("id")
            for item in self._decisions
            if isinstance(item.get("id"), int)
            and not isinstance(item.get("id"), bool)
            and item.get("id") > 0
        ]
        return max(existing_ids, default=0) + 1

    def _normalise_order(self) -> None:
        for order, decision in enumerate(self._decisions, start=1):
            decision["order"] = order

    def add(self, name: str) -> int:
        """Append a new, basic folder classification and return its ID."""
        normalized_name = str(name or "").strip()
        if not normalized_name:
            raise ValueError("A classification name is required")

        decision_id = self._next_id()
        decision = {
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
        }
        self._decisions.append(decision)
        self._normalise_order()
        return decision_id

    def duplicate(self, decision_id: int, name: str) -> int:
        """Insert an independent copy immediately after its source decision."""
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
        duplicate["order"] = source_index + 2
        self._decisions.insert(source_index + 1, duplicate)
        self._normalise_order()
        return new_id

    def delete(self, decision_id: int) -> None:
        """Delete a user-managed decision; the Keep action is protected."""
        index = self._index_of(decision_id)
        decision = self._decisions[index]
        if decision.get("handler") == "keep":
            raise ValueError("The Keep classification cannot be deleted")
        del self._decisions[index]
        self._normalise_order()

    def set_enabled(self, decision_id: int, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("enabled must be a boolean")
        self._decisions[self._index_of(decision_id)]["enabled"] = enabled

    def move(self, decision_id: int, offset: int) -> None:
        """Move a decision one position up or down."""
        if offset not in (-1, 1):
            raise ValueError("offset must be -1 or 1")
        index = self._index_of(decision_id)
        target = index + offset
        if target < 0 or target >= len(self._decisions):
            return
        self._decisions[index], self._decisions[target] = (
            self._decisions[target],
            self._decisions[index],
        )
        self._normalise_order()
