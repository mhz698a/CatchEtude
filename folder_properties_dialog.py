"""
Folder Properties dialog for CatchEtude.

The dialog never starts a scan during construction or display. The user chooses
the traditional filesystem traversal or the NTFS MFT-backed scanner explicitly;
both run in a worker thread and report incremental statistics.
"""

import logging
import os
import time
from pathlib import Path
from typing import Callable, Optional

from PyQt6 import QtCore, QtWidgets

from localization import LocalizationManager
from ntfs_mft import (
    ElevationRequiredError,
    MFTError,
    UnsupportedFilesystemError,
    get_volume_info,
    is_process_elevated,
    scan_folder_mft,
)


logger = logging.getLogger(__name__)
_IGNORED_FILES = {"desktop.ini", "thumbs.db"}
_ACTIVE_SCAN_WORKERS = set()


def _scan_folder_stats(
    folder_path: Path,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> tuple[int, int, int, int]:
    """Return (file_count, total_bytes, root_entry_count, folder_mtime_ns)."""
    file_count = 0
    total_size = 0
    root_entry_count = 0
    folder_mtime_ns = 0

    try:
        if not folder_path.is_dir():
            return file_count, total_size, root_entry_count, folder_mtime_ns

        with os.scandir(folder_path) as entries:
            root_entry_count = sum(1 for _ in entries)

        for root, _, filenames in os.walk(
            folder_path,
            onerror=lambda error: logger.warning(
                "Could not scan directory %s: %s",
                getattr(error, "filename", folder_path),
                error,
            ),
        ):
            if should_stop and should_stop():
                break

            for filename in filenames:
                if should_stop and should_stop():
                    break
                if filename.casefold() in _IGNORED_FILES:
                    continue

                file_count += 1
                try:
                    total_size += os.path.getsize(os.path.join(root, filename))
                except OSError as exc:
                    logger.debug(
                        "Could not read size for %s: %s",
                        os.path.join(root, filename),
                        exc,
                    )

                if progress_callback:
                    progress_callback(file_count, total_size)

        try:
            folder_mtime_ns = folder_path.stat().st_mtime_ns
        except OSError as exc:
            logger.debug("Could not read folder timestamp for %s: %s", folder_path, exc)

    except OSError as exc:
        logger.warning("Could not calculate properties for %s: %s", folder_path, exc)

    return file_count, total_size, root_entry_count, folder_mtime_ns


def scan_folder_stats(folder_path: Path) -> tuple[int, int]:
    """Synchronous helper retained for tests and non-UI callers."""
    file_count, total_size, _, _ = _scan_folder_stats(Path(folder_path))
    return file_count, total_size


def format_bytes(total_bytes: int) -> str:
    """Format a byte count using binary units and include the exact byte count."""
    total_bytes = max(0, int(total_bytes))
    if total_bytes < 1024 * 1024:
        return f"{total_bytes / 1024:.1f} KB ({total_bytes:,} bytes)"
    if total_bytes < 1024 * 1024 * 1024:
        return f"{total_bytes / (1024 * 1024):.1f} MB ({total_bytes:,} bytes)"
    return f"{total_bytes / (1024 * 1024 * 1024):.2f} GB ({total_bytes:,} bytes)"


class FolderStatsWorker(QtCore.QThread):
    """Scan a folder off the UI thread and emit incremental statistics."""

    progress = QtCore.pyqtSignal(int, int)
    stats_ready = QtCore.pyqtSignal(int, int, int, int)
    scan_failed = QtCore.pyqtSignal(str)

    def __init__(self, folder_path: Path):
        super().__init__()
        self.folder_path = Path(folder_path)
        self._last_progress_at = 0.0

    def _report_progress(self, file_count: int, total_size: int) -> None:
        # Throttle signal traffic for very large folders while keeping the values live.
        now = time.monotonic()
        if (
            file_count == 1
            or file_count % 25 == 0
            or now - self._last_progress_at >= 0.1
        ):
            self._last_progress_at = now
            self.progress.emit(file_count, total_size)

    def run(self) -> None:
        try:
            result = _scan_folder_stats(
                self.folder_path,
                progress_callback=self._report_progress,
                should_stop=self.isInterruptionRequested,
            )
            if not self.isInterruptionRequested():
                self.stats_ready.emit(*result)
        except Exception as exc:
            logger.exception("Folder properties scan failed for %s", self.folder_path)
            if not self.isInterruptionRequested():
                self.scan_failed.emit(str(exc))




class MFTFolderStatsWorker(QtCore.QThread):
    """Obtain recursive statistics through NTFS MFT records."""

    progress = QtCore.pyqtSignal(str, int, int, int)
    stats_ready = QtCore.pyqtSignal(int, int, int, int, int)
    scan_failed = QtCore.pyqtSignal(str)

    def __init__(self, folder_path: Path):
        super().__init__()
        self.folder_path = Path(folder_path)

    def run(self) -> None:
        try:
            result = scan_folder_mft(
                self.folder_path,
                progress_callback=self._report_progress,
                should_stop=self.isInterruptionRequested,
            )
            if not self.isInterruptionRequested():
                self.stats_ready.emit(
                    result.file_count,
                    result.total_size,
                    result.root_entry_count,
                    result.inaccessible_count,
                    result.records_scanned,
                )
        except Exception as exc:
            logger.exception("MFT folder properties scan failed for %s", self.folder_path)
            if not self.isInterruptionRequested():
                self.scan_failed.emit(str(exc))

    def _report_progress(
        self, phase: str, processed: int, file_count: int, total_size: int
    ) -> None:
        if not self.isInterruptionRequested():
            self.progress.emit(phase, processed, file_count, total_size)


class FolderPropertiesDialog(QtWidgets.QDialog):
    """Display folder and optional character metadata without blocking the UI."""

    def __init__(
        self,
        folder_path: Path,
        char_entry: Optional[object] = None,
        parent=None,
        loc: Optional[LocalizationManager] = None,
        overworld_year: Optional[int] = None,
    ):
        super().__init__(parent)
        self.folder_path = Path(folder_path)
        self.char_entry = char_entry
        self.overworld_year = overworld_year
        self.loc = loc or LocalizationManager()
        self._scan_worker: Optional[QtCore.QThread] = None
        self._scan_mode: Optional[str] = None

        self.setWindowTitle(
            f"{self.loc.get('dlg_properties_title')} - {self.folder_path.name}"
        )
        self.setMinimumWidth(460)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        header = QtWidgets.QLabel(self.folder_path.name)
        font = header.font()
        font.setPointSize(14)
        font.setBold(True)
        header.setFont(font)
        layout.addWidget(header)

        separator = QtWidgets.QFrame()
        separator.setFrameShape(QtWidgets.QFrame.Shape.HLine)
        separator.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        layout.addWidget(separator)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        layout.addWidget(self.progress_bar)

        self.status_label = self._make_label(self.loc.get("lbl_prop_scan_not_started"))
        layout.addWidget(self.status_label)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
        form.setFormAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignTop
        )
        form.setSpacing(8)

        self.files_value = self._make_label("—")
        self.size_value = self._make_label("—")

        form.addRow(
            self._make_label(self.loc.get("lbl_prop_name"), True),
            self._make_label(self.folder_path.name),
        )
        form.addRow(
            self._make_label(self.loc.get("lbl_prop_path"), True),
            self._make_label(str(self.folder_path)),
        )
        form.addRow(self._make_label(self.loc.get("lbl_prop_files"), True), self.files_value)
        form.addRow(self._make_label(self.loc.get("lbl_prop_size"), True), self.size_value)

        if self.char_entry:
            character = self.char_entry
            if getattr(character, "year", None):
                form.addRow(
                    self._make_label(self.loc.get("lbl_prop_year"), True),
                    self._make_label(str(character.year)),
                )
            if getattr(character, "num", None) is not None:
                number = f"{character.num:02d}" if character.num != 0 else "0"
                form.addRow(
                    self._make_label(self.loc.get("lbl_prop_num"), True),
                    self._make_label(number),
                )
            if getattr(character, "name", ""):
                char_name = (
                    character.name
                    if character.name != "_"
                    else getattr(character, "alter", "")
                )
                form.addRow(
                    self._make_label(self.loc.get("lbl_prop_char_name"), True),
                    self._make_label(char_name),
                )
            if getattr(character, "alter", "") and character.alter != "_":
                form.addRow(
                    self._make_label(self.loc.get("lbl_prop_alter"), True),
                    self._make_label(character.alter),
                )
            if getattr(character, "birthday_iso", ""):
                form.addRow(
                    self._make_label(self.loc.get("lbl_prop_birthday"), True),
                    self._make_label(character.birthday_iso),
                )
            if getattr(character, "age_str", ""):
                form.addRow(
                    self._make_label(self.loc.get("lbl_prop_age"), True),
                    self._make_label(character.age_str),
                )

        layout.addLayout(form)
        layout.addStretch()

        button_row = QtWidgets.QHBoxLayout()
        self.traditional_scan_button = QtWidgets.QPushButton(
            self.loc.get("btn_prop_scan_traditional")
        )
        self.traditional_scan_button.clicked.connect(self._start_traditional_scan)
        button_row.addWidget(self.traditional_scan_button)

        self.mft_scan_button = QtWidgets.QPushButton(
            self.loc.get("btn_prop_scan_mft")
        )
        self.mft_scan_button.setToolTip(self.loc.get("tooltip_prop_scan_mft"))
        self.mft_scan_button.clicked.connect(self._start_mft_scan)
        button_row.addWidget(self.mft_scan_button)

        button_row.addStretch()
        close_button = QtWidgets.QPushButton(self.loc.get("btn_close"))
        close_button.setFixedWidth(100)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

    def _prepare_scan(self, mode: str) -> bool:
        if self._scan_worker is not None:
            return False

        self._scan_mode = mode
        self.files_value.setText("0")
        self.size_value.setText(format_bytes(0))
        self.status_label.setText(
            self.loc.get(
                "lbl_prop_mft_indexing" if mode == "mft"
                else "lbl_prop_traditional_scanning"
            )
        )
        self.progress_bar.setRange(0, 0)
        self.progress_bar.show()
        self.traditional_scan_button.setEnabled(False)
        self.mft_scan_button.setEnabled(False)
        return True

    def _attach_scan_worker(self, worker: QtCore.QThread) -> None:
        self._scan_worker = worker
        _ACTIVE_SCAN_WORKERS.add(worker)
        # Global cleanup must outlive the dialog; UI updates use a QObject-bound
        # slot so Qt disconnects them automatically if the dialog is destroyed.
        worker.finished.connect(
            lambda current=worker: _ACTIVE_SCAN_WORKERS.discard(current)
        )
        worker.finished.connect(self._on_scan_worker_finished)
        worker.start()

    def _start_traditional_scan(self) -> None:
        if not self._prepare_scan("traditional"):
            return

        worker = FolderStatsWorker(self.folder_path)
        worker.progress.connect(self._on_scan_progress)
        worker.stats_ready.connect(self._on_scan_ready)
        worker.scan_failed.connect(self._on_scan_failed)
        self._attach_scan_worker(worker)

    def _start_mft_scan(self) -> None:
        if self._scan_worker is not None:
            return

        try:
            volume = get_volume_info(self.folder_path)
        except MFTError as exc:
            QtWidgets.QMessageBox.warning(
                self, self.loc.get("dlg_properties_title"), str(exc)
            )
            return
        except OSError as exc:
            logger.exception("Could not identify filesystem for %s", self.folder_path)
            QtWidgets.QMessageBox.warning(
                self,
                self.loc.get("dlg_properties_title"),
                self.loc.get("msg_prop_mft_volume_error").format(error=exc),
            )
            return

        if volume.filesystem.casefold() != "ntfs":
            QtWidgets.QMessageBox.information(
                self,
                self.loc.get("dlg_properties_title"),
                self.loc.get("msg_prop_mft_unsupported_fs").format(
                    filesystem=volume.filesystem or self.loc.get("unknown_value")
                ),
            )
            return

        try:
            elevated = is_process_elevated()
        except MFTError as exc:
            QtWidgets.QMessageBox.warning(
                self, self.loc.get("dlg_properties_title"), str(exc)
            )
            return
        except OSError as exc:
            logger.exception("Could not inspect process elevation")
            QtWidgets.QMessageBox.warning(
                self,
                self.loc.get("dlg_properties_title"),
                self.loc.get("msg_prop_mft_elevation_check_error").format(error=exc),
            )
            return

        if not elevated:
            QtWidgets.QMessageBox.warning(
                self,
                self.loc.get("dlg_properties_title"),
                self.loc.get("msg_prop_admin_required"),
            )
            return

        if not self._prepare_scan("mft"):
            return

        worker = MFTFolderStatsWorker(self.folder_path)
        worker.progress.connect(self._on_mft_scan_progress)
        worker.stats_ready.connect(self._on_mft_scan_ready)
        worker.scan_failed.connect(self._on_scan_failed)
        self._attach_scan_worker(worker)

    @QtCore.pyqtSlot()
    def _on_scan_worker_finished(self) -> None:
        worker = self.sender()
        if worker is self._scan_worker:
            self._scan_worker = None
            self.traditional_scan_button.setEnabled(True)
            self.mft_scan_button.setEnabled(True)

    def _on_mft_scan_progress(
        self, phase: str, processed: int, file_count: int, total_size: int
    ) -> None:
        self.files_value.setText(str(file_count))
        self.size_value.setText(format_bytes(total_size))
        if phase == "index":
            self.status_label.setText(
                self.loc.get("lbl_prop_mft_indexing").format(records=processed)
            )
        else:
            self.status_label.setText(
                self.loc.get("lbl_prop_mft_counting").format(files=processed)
            )

    @QtCore.pyqtSlot(int, int)
    def _on_scan_progress(self, file_count: int, total_size: int) -> None:
        self.files_value.setText(str(file_count))
        self.size_value.setText(format_bytes(total_size))

    @QtCore.pyqtSlot(int, int, int, int)
    def _on_scan_ready(
        self, file_count: int, total_size: int, entry_count: int, folder_mtime_ns: int
    ) -> None:
        self._on_scan_progress(file_count, total_size)
        self.progress_bar.hide()
        self.status_label.setText(self.loc.get("lbl_prop_scan_complete"))
        self._update_folder_cache(
            file_count, total_size, entry_count, folder_mtime_ns
        )

    @QtCore.pyqtSlot(int, int, int, int, int)
    def _on_mft_scan_ready(
        self,
        file_count: int,
        total_size: int,
        entry_count: int,
        inaccessible_count: int,
        records_scanned: int,
    ) -> None:
        self._on_scan_progress(file_count, total_size)
        self.progress_bar.hide()

        if inaccessible_count:
            self.status_label.setText(
                self.loc.get("lbl_prop_mft_partial").format(
                    inaccessible=inaccessible_count,
                    records=records_scanned,
                )
            )
            logger.warning(
                "MFT scan for %s could not read sizes for %s files",
                self.folder_path,
                inaccessible_count,
            )
            return

        self.status_label.setText(
            self.loc.get("lbl_prop_mft_complete").format(records=records_scanned)
        )
        try:
            folder_mtime_ns = self.folder_path.stat().st_mtime_ns
        except OSError:
            folder_mtime_ns = 0
        self._update_folder_cache(
            file_count, total_size, entry_count, folder_mtime_ns
        )

    @QtCore.pyqtSlot(str)
    def _on_scan_failed(self, error_message: str) -> None:
        self.progress_bar.hide()
        self.status_label.setText(self.loc.get("lbl_prop_scan_error"))
        logger.error(
            "Unable to calculate properties for %s: %s",
            self.folder_path,
            error_message,
        )

    def _update_folder_cache(
        self,
        file_count: int,
        total_size: int,
        entry_count: int,
        folder_mtime_ns: int,
    ) -> None:
        if not folder_mtime_ns:
            return

        # Overworld cache entries are refreshed only when Properties is opened;
        # subfolder-button rendering itself performs no recursive filesystem I/O.
        if self.overworld_year is not None:
            try:
                from overworld_cache_mgr import OverworldCacheManager

                cache = OverworldCacheManager(self.overworld_year)
                cache.update_folder(
                    str(self.folder_path),
                    folder_mtime_ns,
                    file_count,
                    total_size,
                    f"{total_size / (1024 * 1024):.1f} MB",
                )
                cache.save()
            except Exception:
                logger.exception(
                    "Could not update Overworld cache for %s", self.folder_path
                )
            return

        character = self.char_entry
        if not character:
            return

        year = getattr(character, "year", None)
        if not year:
            return

        try:
            from character_cache_mgr import CharacterCacheManager

            cache = CharacterCacheManager(year)
            metadata = {
                "num": getattr(character, "num", 0),
                "alter": getattr(character, "alter", ""),
                "name": getattr(character, "name", ""),
                "birthday_iso": getattr(character, "birthday_iso", "1970-01-01"),
                "origin_age": getattr(character, "origin_age", 0),
            }
            size_mb = f"{total_size / (1024 * 1024):.1f} MB"
            cache.update_folder(
                str(self.folder_path),
                folder_mtime_ns,
                entry_count,
                file_count,
                total_size,
                metadata,
                getattr(character, "age_str", ""),
                size_mb,
            )
            cache.save()
        except Exception:
            logger.exception("Could not update character cache for %s", self.folder_path)

    def _make_label(self, text: str, bold: bool = False) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        if bold:
            font = label.font()
            font.setBold(True)
            label.setFont(font)
        return label

    def closeEvent(self, event) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.requestInterruption()
        super().closeEvent(event)
