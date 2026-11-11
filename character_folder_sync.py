"""Synchronize character-style folders across JSON-driven decisions.

Synchronization operates on directory entries only. It never copies files or
merges folder contents.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from character_metadata import is_character_folder_name


@dataclass
class CharacterFolderSyncReport:
    """Outcome of one multi-classification folder synchronization."""

    created: list[Path] = field(default_factory=list)
    renamed: list[tuple[Path, Path]] = field(default_factory=list)
    existing: list[Path] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def failed_count(self) -> int:
        return len(self.conflicts) + len(self.errors)


def is_character_metadata_folder(decision: dict[str, Any] | None, folder_name: str) -> bool:
    """Whether this folder is eligible for character-only synchronization.

    A decision may use character metadata for generic folder labels too. Those
    labels still receive a second line, but only encoded character folder names
    expose the synchronization action.
    """
    return bool(
        decision
        and decision.get("behaviour_second_line") == "character_metadata"
        and is_character_folder_name(folder_name)
    )


def validate_character_folder_name(name: str) -> str:
    """Return a safe single directory name or raise ValueError."""
    if not isinstance(name, str):
        raise ValueError("Folder name must be text")

    name = name.strip()
    invalid_characters = '<>:"/\\|?*'
    if (
        not name
        or name in {".", ".."}
        or any(ord(char) < 32 or char in invalid_characters for char in name)
        or name.endswith((".", " "))
        or Path(name).is_absolute()
        or Path(name).name != name
    ):
        raise ValueError(f"Invalid folder name: {name!r}")

    return name


def get_character_metadata_decisions(registry: Any) -> list[dict[str, Any]]:
    """Return all configured filesystem decisions using character metadata.

    Disabled decisions are included too: when a definition is enabled later,
    its folder tree is already synchronized with the other definitions.
    """
    decisions = [
        decision
        for decision in getattr(registry, "decisions", ())
        if decision.get("behaviour_second_line") == "character_metadata"
        and decision.get("handler") == "move_to_subfolder"
        and decision.get("folder_source") == "filesystem"
    ]
    return sorted(
        decisions,
        key=lambda decision: (decision.get("order", 0), decision.get("id", 0)),
    )


def _path_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _target_roots(
    registry: Any,
    dispatcher: Any,
    year: int,
    source_decision_id: int,
    source_base: Path | None,
    report: CharacterFolderSyncReport,
):
    """Yield unique destination roots, excluding the initiating decision/root."""
    seen_roots = {_path_key(Path(source_base))} if source_base is not None else set()

    for decision in get_character_metadata_decisions(registry):
        if decision.get("id") == source_decision_id:
            continue

        try:
            base = dispatcher.resolve_base_path(decision, year)
            if base is None:
                raise ValueError("The decision has no resolvable base path")
            base = Path(base)
        except Exception as exc:
            message = (
                f"Decision {decision.get('id')}: could not resolve its folder path: {exc}"
            )
            report.errors.append(message)
            logging.warning(message, exc_info=True)
            continue

        key = _path_key(base)
        if key in seen_roots:
            continue
        seen_roots.add(key)
        yield decision, base


def sync_character_folder_to_others(
    registry: Any,
    dispatcher: Any,
    year: int,
    folder_name: str,
    source_decision_id: int,
    source_base: Path | None = None,
) -> CharacterFolderSyncReport:
    """Create an empty same-named folder in every other metadata decision."""
    name = validate_character_folder_name(folder_name)
    if year is None:
        raise ValueError("A year must be selected for character folder synchronization")

    report = CharacterFolderSyncReport()
    for decision, base in _target_roots(
        registry, dispatcher, int(year), source_decision_id, source_base, report
    ):
        destination = base / name
        try:
            base.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                if destination.is_dir():
                    report.existing.append(destination)
                else:
                    message = f"A file already occupies the folder path: {destination}"
                    report.conflicts.append(message)
                    logging.warning(message)
                continue

            destination.mkdir()
            report.created.append(destination)
        except FileExistsError:
            # Another process may have created this folder after the initial check.
            if destination.is_dir():
                report.existing.append(destination)
            else:
                message = f"A file already occupies the folder path: {destination}"
                report.conflicts.append(message)
                logging.warning(message)
        except OSError as exc:
            message = f"Decision {decision.get('id')}: could not create {destination}: {exc}"
            report.errors.append(message)
            logging.warning(message, exc_info=True)

    return report


def sync_renamed_character_folder(
    registry: Any,
    dispatcher: Any,
    year: int,
    old_name: str,
    new_name: str,
    source_decision_id: int,
    source_base: Path | None = None,
) -> CharacterFolderSyncReport:
    """Propagate a rename, or create the new empty folder where the old one is absent.

    If an old counterpart exists, its directory is renamed in place, preserving
    its own contents. No data is copied between classifications. If the new
    name already exists alongside the old name, neither directory is removed.
    """
    old_name = validate_character_folder_name(old_name)
    new_name = validate_character_folder_name(new_name)
    if year is None:
        raise ValueError("A year must be selected for character folder synchronization")

    report = CharacterFolderSyncReport()
    for decision, base in _target_roots(
        registry, dispatcher, int(year), source_decision_id, source_base, report
    ):
        old_path = base / old_name
        new_path = base / new_name

        try:
            if new_path.exists():
                if not new_path.is_dir():
                    message = f"A file already occupies the new folder path: {new_path}"
                    report.conflicts.append(message)
                    logging.warning(message)
                elif old_path.exists():
                    message = (
                        f"Both old and new folders exist in decision "
                        f"{decision.get('id')}: {old_path} / {new_path}"
                    )
                    report.conflicts.append(message)
                    logging.warning(message)
                else:
                    report.existing.append(new_path)
                continue

            if old_path.exists():
                if not old_path.is_dir():
                    message = f"The old folder path is not a directory: {old_path}"
                    report.conflicts.append(message)
                    logging.warning(message)
                    continue
                old_path.rename(new_path)
                report.renamed.append((old_path, new_path))
                continue

            base.mkdir(parents=True, exist_ok=True)
            new_path.mkdir()
            report.created.append(new_path)
        except FileExistsError:
            if new_path.is_dir() and not old_path.exists():
                report.existing.append(new_path)
            else:
                message = f"Folder rename conflict in decision {decision.get('id')}: {new_path}"
                report.conflicts.append(message)
                logging.warning(message)
        except OSError as exc:
            message = (
                f"Decision {decision.get('id')}: could not synchronize "
                f"{old_name!r} to {new_path}: {exc}"
            )
            report.errors.append(message)
            logging.warning(message, exc_info=True)

    return report
