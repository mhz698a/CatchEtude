"""
GUI Runner and Non-Modal Progress Dialog for PDF Operations in CatchEtude.
Ejecutor GUI y diálogo de progreso no modal para operaciones de PDF en CatchEtude.
"""

import logging
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot

import config
import pdf_tools_mgr
from utils import resolve_duplicate


class PDFWorkerThread(QThread):
    """
    Background worker thread executing PDF tasks without freezing the GUI.
    """
    progress_updated = pyqtSignal(int, int)  # current, total
    finished_success = pyqtSignal(list, list)  # produced_files in temp, warning_messages
    finished_error = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(
        self,
        task_type: str,
        files: List[Path],
        dpi: int = 150,
        parent: Optional[QtCore.QObject] = None
    ):
        super().__init__(parent)
        self.task_type = task_type
        self.files = files
        self.dpi = dpi
        self._is_cancelled = False

    def request_cancellation(self):
        self._is_cancelled = True

    def _check_cancelled(self) -> bool:
        return self._is_cancelled

    def cleanup_temp(self):
        if hasattr(self, "temp_dir_obj") and self.temp_dir_obj:
            try:
                self.temp_dir_obj.cleanup()
            except Exception as e:
                logging.debug(f"Error cleaning up temp directory: {e}")
            self.temp_dir_obj = None

    def run(self):
        self.temp_dir_obj = tempfile.TemporaryDirectory()
        temp_dir = Path(self.temp_dir_obj.name)

        try:
            warnings: List[str] = []
            produced_temp_files: List[Path] = []

            def _progress(cur, tot):
                self.progress_updated.emit(cur, tot)

            if self.task_type == "imgs_to_pdf":
                out_file = pdf_tools_mgr.images_to_pdf(
                    self.files,
                    temp_dir,
                    cancel_check=self._check_cancelled,
                    progress_cb=_progress
                )
                produced_temp_files.append(out_file)

            elif self.task_type == "pdf_to_jpeg":
                produced_temp_files = pdf_tools_mgr.pdf_to_jpeg(
                    self.files,
                    temp_dir,
                    dpi=self.dpi,
                    cancel_check=self._check_cancelled,
                    progress_cb=_progress
                )

            elif self.task_type == "extract_images":
                produced_temp_files, warnings = pdf_tools_mgr.extract_pdf_images(
                    self.files,
                    temp_dir,
                    cancel_check=self._check_cancelled,
                    progress_cb=_progress
                )

            elif self.task_type == "merge_pdfs":
                out_file = pdf_tools_mgr.merge_pdfs(
                    self.files,
                    temp_dir,
                    cancel_check=self._check_cancelled,
                    progress_cb=_progress
                )
                produced_temp_files.append(out_file)

            else:
                raise ValueError(f"Unknown PDF task type: {self.task_type}")

            if self._is_cancelled:
                self.cancelled.emit()
            else:
                self.finished_success.emit(produced_temp_files, warnings)

        except InterruptedError:
            logging.info("PDF worker process cancelled by user")
            self.cancelled.emit()
        except Exception as e:
            logging.exception("Error executing PDF task in worker thread")
            if not self._is_cancelled:
                self.finished_error.emit(str(e))
            else:
                self.cancelled.emit()
        finally:
            # Note: TemporaryDirectory will be cleaned up on deletion
            pass


class PDFProgressDialog(QtWidgets.QDialog):
    """
    Non-modal progress dialog allowing CatchEtude to remain interactive.
    """
    def __init__(self, title: str, task_type: str, files: List[Path], parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(380)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self.task_type = task_type
        self.files = files
        self.worker: Optional[PDFWorkerThread] = None

        self._build_ui()

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        self.lbl_status = QtWidgets.QLabel("Procesando...")
        layout.addWidget(self.lbl_status)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        self.btn_cancel = QtWidgets.QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

    def start_task(self, dpi: int = 150):
        self.worker = PDFWorkerThread(self.task_type, self.files, dpi=dpi, parent=self)
        self.worker.progress_updated.connect(self._on_progress_updated)
        self.worker.finished_success.connect(self._on_finished_success)
        self.worker.finished_error.connect(self._on_finished_error)
        self.worker.cancelled.connect(self._on_cancelled)
        self.show()
        self.worker.start()

    @pyqtSlot(int, int)
    def _on_progress_updated(self, cur: int, tot: int):
        if tot > 0:
            val = int((cur / tot) * 100)
            self.progress_bar.setValue(val)
            self.lbl_status.setText(f"Procesando ({cur}/{tot})...")

    @pyqtSlot(list, list)
    def _on_finished_success(self, temp_files: List[Path], warnings: List[str]):
        downloads_dir = config.DOWNLOADS
        downloads_dir.mkdir(parents=True, exist_ok=True)

        moved_count = 0
        for src_path in temp_files:
            if not src_path.exists():
                continue
            dest_candidate = downloads_dir / src_path.name
            dest_path = resolve_duplicate(dest_candidate)
            try:
                shutil.move(str(src_path), str(dest_path))
                moved_count += 1
            except Exception as e:
                logging.exception(f"Failed to move {src_path} to downloads: {e}")

        self.close()

        if self.worker:
            self.worker.cleanup_temp()

        # Handle UI notifications on main thread
        if self.task_type == "extract_images":
            if moved_count == 0:
                QtWidgets.QMessageBox.information(
                    self.parentWidget(),
                    "Extraer imágenes",
                    "No se encontraron imágenes incrustadas en el PDF."
                )
            elif warnings:
                warn_msg = "\n".join(warnings)
                QtWidgets.QMessageBox.warning(
                    self.parentWidget(),
                    "Extraer imágenes",
                    f"Imágenes extraídas con algunas advertencias:\n{warn_msg}"
                )

    @pyqtSlot(str)
    def _on_finished_error(self, err_msg: str):
        if self.worker:
            self.worker.cleanup_temp()
        self.close()
        QtWidgets.QMessageBox.critical(
            self.parentWidget(),
            "Error en PDF",
            f"Ocurrió un error al procesar el archivo PDF:\n{err_msg}"
        )

    @pyqtSlot()
    def _on_cancelled(self):
        if self.worker:
            self.worker.cleanup_temp()
        self.close()

    def _on_cancel_clicked(self):
        if self.worker and self.worker.isRunning():
            self.lbl_status.setText("Cancelando...")
            self.btn_cancel.setEnabled(False)
            self.worker.request_cancellation()

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.request_cancellation()
            self.worker.wait(3000)
        event.accept()


def run_pdf_task(
    parent_widget: Optional[QtWidgets.QWidget],
    task_type: str,
    files: List[Path],
    title: str
):
    """
    Launches non-modal PDF operation dialog and background worker.
    """
    dpi = getattr(config, "PDF_DPI", 150)
    dialog = PDFProgressDialog(title, task_type, files, parent=parent_widget)
    dialog.start_task(dpi=dpi)
    return dialog
