"""Regression tests for contextual PDF plugin actions."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


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
