"""MFT-backed recursive folder statistics for local NTFS volumes."""

from __future__ import annotations

import os
import sqlite3
import struct
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .errors import (
    ElevationRequiredError,
    MFTEnumerationError,
    MFTRecordVersionError,
    MFTScanCancelled,
    UnsupportedFilesystemError,
)
from .win32 import WindowsVolumeApi

FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_IGNORED_NAMES = {"desktop.ini", "thumbs.db"}
_DEFAULT_BUFFER_SIZE = 1024 * 1024
_USN_V2_HEADER_SIZE = 60


@dataclass(frozen=True)
class MFTEntry:
    file_reference: int
    parent_reference: int
    name: str
    attributes: int

    @property
    def is_directory(self) -> bool:
        return bool(self.attributes & FILE_ATTRIBUTE_DIRECTORY)

    @property
    def is_reparse_point(self) -> bool:
        return bool(self.attributes & FILE_ATTRIBUTE_REPARSE_POINT)


@dataclass(frozen=True)
class MFTScanResult:
    file_count: int
    total_size: int
    root_entry_count: int
    inaccessible_count: int
    records_scanned: int

    @property
    def complete(self) -> bool:
        return self.inaccessible_count == 0


def parse_usn_enum_buffer(buffer: bytes) -> tuple[int, list[MFTEntry]]:
    """Decode one FSCTL_ENUM_USN_DATA output page.

    The first eight bytes contain the next StartFileReferenceNumber. Following
    bytes contain self-sized USN_RECORD_V2 entries. Unknown record versions or
    inconsistent offsets are rejected instead of being silently miscounted.
    """
    if len(buffer) < 8:
        raise MFTEnumerationError("La respuesta MFT es menor que el encabezado esperado.")

    next_reference = struct.unpack_from("<Q", buffer, 0)[0]
    entries: list[MFTEntry] = []
    offset = 8

    while offset < len(buffer):
        remaining = len(buffer) - offset
        if remaining < 8:
            if any(buffer[offset:]):
                raise MFTEnumerationError("Datos residuales inválidos al final de una página MFT.")
            break

        record_length, major, minor = struct.unpack_from("<IHH", buffer, offset)
        if record_length == 0:
            if any(buffer[offset:]):
                raise MFTEnumerationError("Se encontró un registro MFT de longitud cero.")
            break
        if record_length < _USN_V2_HEADER_SIZE or record_length > remaining:
            raise MFTEnumerationError("Longitud de registro USN fuera de los límites del búfer.")
        if major != 2 or minor != 0:
            raise MFTRecordVersionError(
                f"Versión de registro USN no compatible: {major}.{minor}."
            )

        file_reference, parent_reference = struct.unpack_from("<QQ", buffer, offset + 8)
        attributes = struct.unpack_from("<I", buffer, offset + 52)[0]
        name_length, name_offset = struct.unpack_from("<HH", buffer, offset + 56)

        if name_length % 2:
            raise MFTEnumerationError("La longitud UTF-16 del nombre MFT no es par.")
        if name_offset < _USN_V2_HEADER_SIZE:
            raise MFTEnumerationError("El desplazamiento del nombre invade el encabezado USN.")
        if name_offset + name_length > record_length:
            raise MFTEnumerationError("El nombre USN excede el tamaño del registro.")

        try:
            name = buffer[
                offset + name_offset:offset + name_offset + name_length
            ].decode("utf-16-le", errors="strict")
        except UnicodeDecodeError as exc:
            raise MFTEnumerationError("El nombre de un registro MFT no es UTF-16 válido.") from exc

        if name and name not in (".", ".."):
            entries.append(
                MFTEntry(
                    file_reference=file_reference,
                    parent_reference=parent_reference,
                    name=name,
                    attributes=attributes,
                )
            )
        offset += record_length

    return next_reference, entries


class MFTScanner:
    """Index MFT records into a temporary SQLite database and scan one subtree.

    SQLite keeps the full-volume index disk-backed, avoiding an unbounded Python
    dictionary when the volume contains millions of MFT records.
    """

    def __init__(
        self,
        api=None,
        buffer_size: int = _DEFAULT_BUFFER_SIZE,
        progress_callback: Optional[Callable[[str, int, int, int], None]] = None,
        should_stop: Optional[Callable[[], bool]] = None,
    ):
        self.api = api or WindowsVolumeApi()
        self.buffer_size = max(64 * 1024, int(buffer_size))
        self.progress_callback = progress_callback
        self.should_stop = should_stop

    def _check_cancelled(self) -> None:
        if self.should_stop and self.should_stop():
            raise MFTScanCancelled("El escaneo MFT fue cancelado.")

    def _report(self, phase: str, processed: int, file_count: int, total_size: int) -> None:
        if self.progress_callback:
            self.progress_callback(phase, processed, file_count, total_size)

    @staticmethod
    def _frn_blob(reference: int) -> bytes:
        return struct.pack("<Q", reference)

    def scan_folder(self, folder_path: Path) -> MFTScanResult:
        folder = Path(folder_path).resolve()
        if not folder.is_dir():
            raise MFTEnumerationError(f"La ruta no es una carpeta: {folder}")

        volume = self.api.get_volume_info(folder)
        if volume.filesystem.casefold() != "ntfs":
            raise UnsupportedFilesystemError(volume.filesystem)

        if not self.api.is_process_elevated():
            raise ElevationRequiredError(
                "El escaneo MFT requiere que CatchEtude se ejecute como administrador."
            )

        root_reference = self.api.get_file_reference(folder)
        volume_handle = self.api.open_volume(volume)
        try:
            with tempfile.TemporaryDirectory(prefix="catchetude-mft-") as temporary:
                database_path = Path(temporary) / "mft-index.sqlite3"
                with sqlite3.connect(str(database_path)) as connection:
                    connection.execute("PRAGMA journal_mode=OFF")
                    connection.execute("PRAGMA synchronous=OFF")
                    connection.execute("PRAGMA temp_store=MEMORY")
                    connection.execute("PRAGMA cache_size=-32768")
                    connection.execute(
                        "CREATE TABLE entries ("
                        "file_ref BLOB NOT NULL, parent_ref BLOB NOT NULL, "
                        "name TEXT NOT NULL, attributes INTEGER NOT NULL, "
                        "UNIQUE(file_ref, parent_ref, name))"
                    )
                    connection.execute(
                        "CREATE INDEX entries_by_parent ON entries(parent_ref)"
                    )
                    records_scanned = self._index_volume(
                        volume_handle, connection
                    )
                    return self._scan_index(
                        volume_handle, connection, root_reference, records_scanned
                    )
        finally:
            self.api.close_handle(volume_handle)

    def _index_volume(self, volume_handle, connection: sqlite3.Connection) -> int:
        start_reference = 0
        records_scanned = 0
        last_report = 0.0
        batch: list[tuple[bytes, bytes, str, int]] = []

        while True:
            self._check_cancelled()
            raw_page = self.api.enumerate_usn_data(
                volume_handle, start_reference, self.buffer_size
            )
            if raw_page is None:
                break

            next_reference, entries = parse_usn_enum_buffer(raw_page)
            if not entries:
                if next_reference == start_reference:
                    break
                if next_reference <= start_reference:
                    raise MFTEnumerationError(
                        "La enumeración MFT no avanzó al solicitar la siguiente página."
                    )
                start_reference = next_reference
                continue

            for entry in entries:
                batch.append((
                    self._frn_blob(entry.file_reference),
                    self._frn_blob(entry.parent_reference),
                    entry.name,
                    entry.attributes,
                ))
                records_scanned += 1
                if len(batch) >= 4000:
                    connection.executemany(
                        "INSERT OR IGNORE INTO entries VALUES (?, ?, ?, ?)", batch
                    )
                    batch.clear()

            if batch:
                connection.executemany(
                    "INSERT OR IGNORE INTO entries VALUES (?, ?, ?, ?)", batch
                )
                batch.clear()

            now = time.monotonic()
            if now - last_report >= 0.15:
                self._report("index", records_scanned, 0, 0)
                last_report = now

            if next_reference <= start_reference:
                raise MFTEnumerationError(
                    "La enumeración MFT devolvió un identificador de continuación inválido."
                )
            start_reference = next_reference

        connection.commit()
        self._report("index", records_scanned, 0, 0)
        return records_scanned

    def _scan_index(
        self,
        volume_handle,
        connection: sqlite3.Connection,
        root_reference: int,
        records_scanned: int,
    ) -> MFTScanResult:
        root_blob = self._frn_blob(root_reference)
        root_entry_count = connection.execute(
            "SELECT COUNT(*) FROM entries WHERE parent_ref = ?", (root_blob,)
        ).fetchone()[0]

        directories = deque([root_blob])
        visited_directories = {root_blob}
        file_count = 0
        total_size = 0
        inaccessible_count = 0
        processed_files = 0
        last_report = 0.0

        while directories:
            self._check_cancelled()
            parent_reference = directories.popleft()
            cursor = connection.execute(
                "SELECT file_ref, name, attributes FROM entries WHERE parent_ref = ?",
                (parent_reference,),
            )
            for child_reference, name, attributes in cursor:
                self._check_cancelled()
                if name.casefold() in _IGNORED_NAMES:
                    continue

                is_directory = bool(attributes & FILE_ATTRIBUTE_DIRECTORY)
                is_reparse_point = bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)

                if is_directory:
                    # Do not cross junctions/symlinks: traditional os.walk does not
                    # follow directory symlinks by default either.
                    if not is_reparse_point and child_reference not in visited_directories:
                        visited_directories.add(child_reference)
                        directories.append(child_reference)
                    continue

                file_count += 1
                processed_files += 1
                try:
                    total_size += self.api.get_file_size_by_id(
                        volume_handle, struct.unpack("<Q", child_reference)[0]
                    )
                except OSError:
                    inaccessible_count += 1

                now = time.monotonic()
                if now - last_report >= 0.1:
                    self._report(
                        "count",
                        processed_files,
                        file_count,
                        total_size,
                    )
                    last_report = now

        self._report("count", processed_files, file_count, total_size)
        return MFTScanResult(
            file_count=file_count,
            total_size=total_size,
            root_entry_count=int(root_entry_count),
            inaccessible_count=inaccessible_count,
            records_scanned=records_scanned,
        )


def get_volume_info(path: Path, api=None):
    """Return the filesystem name for a path without opening the MFT."""
    api = api or WindowsVolumeApi()
    return api.get_volume_info(Path(path))


def is_process_elevated(api=None) -> bool:
    """Return whether the current Windows process token is elevated."""
    api = api or WindowsVolumeApi()
    return api.is_process_elevated()


def scan_folder_mft(
    folder_path: Path,
    progress_callback=None,
    should_stop=None,
    api=None,
) -> MFTScanResult:
    """Convenience API for reusable MFT folder scans."""
    return MFTScanner(
        api=api,
        progress_callback=progress_callback,
        should_stop=should_stop,
    ).scan_folder(Path(folder_path))
