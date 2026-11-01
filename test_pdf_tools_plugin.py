"""Regression tests for contextual PDF plugin actions."""

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

from plugin_api import parse_and_validate_plugin_file


PLUGIN_PATH = Path(__file__).parent / "plugins" / "pdf_tools_plugin.py"


def load_pdf_plugin():
    spec = importlib.util.spec_from_file_location("test_pdf_tools_plugin", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeContext:
    def __init__(self):
        self.handlers = {}

    def log(self, *_args):
        pass

    def on_command(self, name, handler):
        self.handlers[name] = handler

    def on_stop(self, _handler):
        pass

    def emit_ready(self):
        pass


class TestPdfToolsPlugin(unittest.TestCase):
    def setUp(self):
        self.module = load_pdf_plugin()
        self.ctx = FakeContext()
        self.module.run_plugin(self.ctx)

    def test_manifest_version_and_conversion_actions_are_valid(self):
        manifest, error = parse_and_validate_plugin_file(str(PLUGIN_PATH))
        self.assertIsNone(error)
        self.assertEqual(manifest["plugin"]["version"], "1.2.0")

        tray_commands = {item["command"] for item in manifest.get("tray_actions", [])}
        self.assertTrue({
            "images_to_ico", "images_to_png", "images_to_jpg",
            "svg_to_png", "svg_to_ico", "audio_to_mp3", "word_to_pdf",
        }.issubset(tray_commands))

        button_commands = {
            item["command"]
            for button in manifest.get("action_buttons", [])
            for item in button.get("menu_items", [])
        }
        self.assertTrue({
            "images_to_ico", "images_to_png", "images_to_jpg",
            "svg_to_png", "svg_to_ico", "audio_to_mp3", "word_to_pdf",
        }.issubset(button_commands))

    def test_word_conversion_dispatch_runs_in_secondary_thread(self):
        runner = sys.modules["catchetude_pdf_tools_gui_runner"]
        observed = {}
        progress_messages = []

        def fake_conversion(task_type, paths, output_dir, cancel_check=None, progress_cb=None):
            observed["task_type"] = task_type
            observed["is_secondary_thread"] = QtCore.QThread.currentThread() != _APP.thread()
            progress_cb(0, 1, "Microsoft Word está exportando el documento…", True)
            return [], []

        worker = runner.PDFWorkerThread("word_to_pdf", [Path("sample.docx")])
        loop = QtCore.QEventLoop()
        worker.progress_updated.connect(
            lambda cur, total, message, busy: progress_messages.append((message, busy))
        )
        worker.finished_success.connect(loop.quit)
        worker.finished_error.connect(lambda _message: loop.quit())

        with patch.object(runner.file_conversion_mgr, "run_file_conversion", side_effect=fake_conversion):
            worker.start()
            QtCore.QTimer.singleShot(10000, loop.quit)
            loop.exec()
            worker.wait(5000)

        worker.cleanup_temp()
        self.assertEqual(observed.get("task_type"), "word_to_pdf")
        self.assertTrue(observed.get("is_secondary_thread"))
        self.assertTrue(any("Microsoft Word está exportando" in message and busy for message, busy in progress_messages))

    def test_all_new_conversion_commands_are_registered(self):
        expected = {
            "images_to_ico",
            "images_to_png",
            "images_to_jpg",
            "svg_to_png",
            "svg_to_ico",
            "audio_to_mp3",
            "word_to_pdf",
        }
        self.assertTrue(expected.issubset(self.ctx.handlers))

    def test_contextual_audio_conversion_uses_selected_path(self):
        selected = Path("/tmp/selected.flac")
        with (
            patch.object(self.module.QFileDialog, "getOpenFileNames") as file_picker,
            patch.object(self.module, "run_pdf_task") as run_task,
        ):
            self.ctx.handlers["audio_to_mp3"]({"paths": [str(selected)]})

        file_picker.assert_not_called()
        run_task.assert_called_once_with(
            None, "audio_to_mp3", [selected], "Audio a MP3"
        )

    def test_contextual_word_conversion_uses_selected_path(self):
        selected = Path("/tmp/document.docx")
        with (
            patch.object(self.module.QFileDialog, "getOpenFileNames") as file_picker,
            patch.object(self.module, "run_pdf_task") as run_task,
        ):
            self.ctx.handlers["word_to_pdf"]({"paths": [str(selected)]})

        file_picker.assert_not_called()
        run_task.assert_called_once_with(
            None, "word_to_pdf", [selected], "Word a PDF"
        )

    def test_contextual_pdf_action_uses_selected_path_without_file_picker(self):
        selected = Path("/tmp/selected.pdf")
        with (
            patch.object(self.module.QFileDialog, "getOpenFileNames") as file_picker,
            patch.object(self.module, "run_pdf_task") as run_task,
        ):
            self.ctx.handlers["pdf_to_jpeg"]({"paths": [str(selected)]})

        file_picker.assert_not_called()
        run_task.assert_called_once_with(
            None, "pdf_to_jpeg", [selected], "Páginas a JPG"
        )

    def test_tray_action_without_context_opens_picker(self):
        selected = "/tmp/selected.pdf"
        with (
            patch.object(
                self.module.QFileDialog, "getOpenFileNames", return_value=([selected], "")
            ) as file_picker,
            patch.object(self.module, "run_pdf_task") as run_task,
        ):
            self.ctx.handlers["extract_images"]({})

        file_picker.assert_called_once()
        run_task.assert_called_once_with(
            None, "extract_images", [Path(selected)], "Extraer imágenes de PDF"
        )


if __name__ == "__main__":
    unittest.main()
