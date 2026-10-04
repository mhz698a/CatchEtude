# /// catch-etude-plugin
# [plugin]
# id = "catchetude.divition-subfolder"
# name = "Divition SubFolder"
# version = "1.0.0"
# api_version = 1
# capabilities = ["ui_action"]
# events = []
#
# [[action_buttons]]
# id = "btn_divide_subfolder"
# label = "Dividir esta carpeta"
# command = "divide_folder"
# target = "subfolder"
# /// end catch-etude-plugin

"""
Divition SubFolder Plugin for CatchEtude.
Splits files in a directory across multiple generated subfolders (_000, _001, ...) with progress feedback.
"""

import math
import shutil
import sys
from pathlib import Path
from PyQt6 import QtCore, QtWidgets
from PyQt6.QtCore import Qt


class SplitFolderWorker(QtCore.QObject):
    """Worker object that executes the folder splitting in a background QThread."""

    progress_changed = QtCore.pyqtSignal(int, int)  # current, total
    finished_signal = QtCore.pyqtSignal(bool, str)  # success, message
    error_signal = QtCore.pyqtSignal(str)

    def __init__(self, target_folder: Path, parts_count: int, parent=None):
        super().__init__(parent)
        self.target_folder = target_folder
        self.parts_count = parts_count
        self._is_cancelled = False

    def stop(self):
        self._is_cancelled = True

    def do_work(self):
        try:
            # Gather files only (not subdirectories)
            files = [f for f in sorted(self.target_folder.iterdir()) if f.is_file()]
            total_files = len(files)
            if total_files == 0:
                self.finished_signal.emit(False, "La carpeta no contiene archivos.")
                return

            base_name = self.target_folder.name
            parent_dir = self.target_folder.parent

            # Create destination folders with _000, _001...
            subfolders = []
            for i in range(self.parts_count):
                part_dir = parent_dir / f"{base_name}_{i:03d}"
                part_dir.mkdir(parents=True, exist_ok=True)
                subfolders.append(part_dir)

            # Move files equitably
            processed = 0
            for idx, file_path in enumerate(files):
                if self._is_cancelled:
                    self.finished_signal.emit(False, "Operación cancelada por el usuario.")
                    return

                dest_dir = subfolders[idx % self.parts_count]
                dest_file = dest_dir / file_path.name
                shutil.move(str(file_path), str(dest_file))

                processed += 1
                self.progress_changed.emit(processed, total_files)

            self.finished_signal.emit(True, f"Se dividieron {total_files} archivos en {self.parts_count} carpetas.")
        except Exception as e:
            self.error_signal.emit(str(e))
            self.finished_signal.emit(False, f"Error dividiendo la carpeta: {e}")


class SplitFolderDialog(QtWidgets.QDialog):
    """Counter dialog to choose the number of divisions."""

    def __init__(self, total_files: int, parent=None):
        super().__init__(parent)
        self.total_files = total_files

        # Determine limits based on rules:
        # min = 2
        # max = 4 if total_files < 100 else max(2, total_files // 50)
        self.min_parts = 2
        if total_files < 100:
            self.max_parts = 4
        else:
            self.max_parts = max(2, total_files // 50)

        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("Dividir carpeta / Divide folder")
        self.setFixedWidth(350)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        layout = QtWidgets.QVBoxLayout(self)

        lbl_info = QtWidgets.QLabel(f"Archivos encontrados: {self.total_files}")
        lbl_info.setStyleSheet("font-weight: bold;")
        layout.addWidget(lbl_info)

        spin_row = QtWidgets.QHBoxLayout()
        spin_row.addWidget(QtWidgets.QLabel("Número de carpetas:"))

        self.spin_parts = QtWidgets.QSpinBox()
        self.spin_parts.setRange(self.min_parts, self.max_parts)
        self.spin_parts.setValue(self.min_parts)
        self.spin_parts.valueChanged.connect(self._update_preview)
        spin_row.addWidget(self.spin_parts)

        layout.addLayout(spin_row)

        self.lbl_preview = QtWidgets.QLabel()
        self.lbl_preview.setWordWrap(True)
        self.lbl_preview.setStyleSheet("color: #007acc; font-weight: bold;")
        layout.addWidget(self.lbl_preview)

        self._update_preview(self.spin_parts.value())

        btn_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _update_preview(self, parts: int):
        if parts <= 0:
            return
        base_count = self.total_files // parts
        remainder = self.total_files % parts
        if remainder == 0:
            text = f"Cada carpeta contendrá {base_count} archivos."
        else:
            text = f"{remainder} carpetas contendrán {base_count + 1} archivos y {parts - remainder} carpetas contendrán {base_count} archivos."
        self.lbl_preview.setText(text)

    def get_parts_count(self) -> int:
        return self.spin_parts.value()


def run_plugin(ctx):
    ctx.log("INFO", "Divition SubFolder plugin initialized.")

    def on_divide_folder(args):
        paths = (args or {}).get("paths", [])
        if not paths:
            ctx.log("WARNING", "No folder path provided for divide_folder.")
            return

        target_path = Path(paths[0])
        if not target_path.exists() or not target_path.is_dir():
            ctx.log("ERROR", f"Target path is not a valid directory: {target_path}")
            return

        files = [f for f in target_path.iterdir() if f.is_file()]
        total_files = len(files)
        if total_files == 0:
            msg = QtWidgets.QMessageBox()
            msg.setWindowTitle("Dividir carpeta")
            msg.setText("La carpeta no contiene archivos para dividir.")
            msg.setIcon(QtWidgets.QMessageBox.Icon.Information)
            msg.exec()
            return

        dlg = SplitFolderDialog(total_files)
        if dlg.exec() != QtWidgets.QDialog.DialogCode.Accepted:
            return

        parts_count = dlg.get_parts_count()
        ctx.log("INFO", f"Splitting folder '{target_path.name}' ({total_files} files) into {parts_count} parts.")

        # Progress dialog
        progress_dlg = QtWidgets.QProgressDialog(
            f"Dividiendo '{target_path.name}'...", "Cancelar", 0, total_files
        )
        progress_dlg.setWindowTitle("Procesando división")
        progress_dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress_dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        progress_dlg.setAutoClose(True)
        progress_dlg.show()

        thread = QtCore.QThread()
        worker = SplitFolderWorker(target_path, parts_count)
        worker.moveToThread(thread)

        # Retain explicit references on plugin function to avoid Python GC
        if not hasattr(run_plugin, "_active_tasks"):
            run_plugin._active_tasks = []
        task_ref = (thread, worker, progress_dlg)
        run_plugin._active_tasks.append(task_ref)

        def cleanup():
            if task_ref in getattr(run_plugin, "_active_tasks", []):
                run_plugin._active_tasks.remove(task_ref)

        thread.started.connect(worker.do_work)

        def on_progress(current, total):
            progress_dlg.setValue(current)

        def on_canceled():
            worker.stop()

        progress_dlg.canceled.connect(on_canceled)

        def on_error(err_msg):
            ctx.log("ERROR", f"Thread error during division: {err_msg}")

        def on_finished(success, message):
            progress_dlg.close()
            ctx.log("INFO" if success else "ERROR", message)
            info_box = QtWidgets.QMessageBox()
            info_box.setWindowTitle("Resultado")
            info_box.setText(message)
            info_box.setIcon(QtWidgets.QMessageBox.Icon.Information if success else QtWidgets.QMessageBox.Icon.Warning)
            info_box.exec()

            thread.quit()

        worker.progress_changed.connect(on_progress)
        worker.error_signal.connect(on_error)
        worker.finished_signal.connect(on_finished)

        # Cleanup memory on thread exit
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(cleanup)

        thread.start()

    ctx.on_command("divide_folder", on_divide_folder)

    def on_stop():
        ctx.log("INFO", "Divition SubFolder plugin stopping.")

    ctx.on_stop(on_stop)
    ctx.emit_ready()
