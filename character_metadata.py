"""Shared parsing and display helpers for folder-name character metadata.

The parser is deliberately permissive: classifications may opt into this
metadata convention even when their folders are not named like characters.
"""
from __future__ import annotations

from datetime import datetime


DEFAULT_BIRTHDAY_ISO = "1970-01-01"


def parse_character_folder_metadata(folder_name: str) -> dict:
    """Parse the optional semicolon metadata encoded after the first period.

    Unknown or non-conforming names remain valid folders. In that case the
    original folder name is kept as the display alias and all other fields
    receive neutral defaults.
    """
    folder_name = str(folder_name or "")
    metadata = {
        "num": 0,
        "alter": folder_name,
        "name": "_",
        "birthday_iso": DEFAULT_BIRTHDAY_ISO,
        "origin_age": 0,
    }

    if "." not in folder_name:
        return metadata

    try:
        raw_metadata = folder_name.split(".", 1)[1]
        parts = [part.strip() for part in raw_metadata.split(";")]

        if len(parts) >= 1 and parts[0] != "_" and parts[0].isdigit():
            metadata["num"] = int(parts[0])
        if len(parts) >= 2 and parts[1] != "_":
            metadata["alter"] = parts[1]
        if len(parts) >= 3 and parts[2] != "_":
            metadata["name"] = parts[2]
        if len(parts) >= 4 and parts[3] not in ("_", None, ""):
            try:
                datetime.fromisoformat(parts[3])
                metadata["birthday_iso"] = parts[3]
            except (TypeError, ValueError):
                pass
        if len(parts) >= 5 and parts[4] != "_" and parts[4].isdigit():
            metadata["origin_age"] = int(parts[4])
    except (TypeError, ValueError, IndexError):
        # Malformed optional metadata must never prevent a folder from loading.
        return {
            "num": 0,
            "alter": folder_name,
            "name": "_",
            "birthday_iso": DEFAULT_BIRTHDAY_ISO,
            "origin_age": 0,
        }

    return metadata


def format_character_metadata_line(folder_name: str, year: int | str) -> str:
    """Format the second line, falling back to the raw folder name.

    This is the same format used by the character list, but works for any
    classification folder and does not depend on the character service.
    """
    metadata = parse_character_folder_metadata(folder_name)

    try:
        birthday = datetime.fromisoformat(metadata["birthday_iso"])
    except (TypeError, ValueError):
        birthday = datetime(1970, 1, 1)

    birthday_text = (
        f" · {birthday.strftime('%Y-%m-%d')}"
        if birthday.year != 1970
        else ""
    )
    number_text = f" · {metadata['num']:02d}" if metadata["num"] else ""
    display_name = (
        metadata["name"]
        if metadata["name"] != "_"
        else metadata["alter"]
    )
    alter_text = (
        f"/{metadata['alter']}"
        if metadata["name"] != "_"
        else ""
    )

    return f"{year}{number_text} · {display_name}{alter_text}{birthday_text}"
