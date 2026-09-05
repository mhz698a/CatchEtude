import unittest
import sys
import ctypes
import importlib.machinery
from pathlib import Path
import tempfile
import shutil

if not hasattr(ctypes, 'windll'):
    class MockWinDLL:
        def __getattr__(self, name):
            class MockDLL:
                def __getattr__(self, func):
                    return lambda *args, **kwargs: 1
            return MockDLL()
    ctypes.windll = MockWinDLL()
    ctypes.WinDLL = lambda name: MockWinDLL()

if not hasattr(ctypes, 'WINFUNCTYPE'):
    ctypes.WINFUNCTYPE = ctypes.CFUNCTYPE

from PyQt6 import QtWidgets, QtCore
import config
from action_panel_mgr import ActionPanel
from queue_panel_mgr import QueuePanel

p = str(Path("settings_dialog.pyw").resolve())
settings_dialog_mod = importlib.machinery.SourceFileLoader("settings_dialog", p).load_module()
SettingsDialog = settings_dialog_mod.SettingsDialog

class TestAutoflatAndUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not QtWidgets.QApplication.instance():
            cls.app = QtWidgets.QApplication([])
        else:
            cls.app = QtWidgets.QApplication.instance()

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.orig_settings_path = config.SETTINGS_PATH
        config.SETTINGS_PATH = Path(self.tmp_dir) / "settings.toml"

    def tearDown(self):
        config.SETTINGS_PATH = self.orig_settings_path
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_autoflat_folders_config_and_settings_dialog(self):
        self.assertIn("AUTOFLAT_FOLDERS", config.DEFAULT_SETTINGS)
        dialog = SettingsDialog()
        self.assertIn("AUTOFLAT_FOLDERS", dialog.inputs)
        line_edit = dialog.inputs["AUTOFLAT_FOLDERS"]
        self.assertEqual(line_edit.placeholderText(), "example_1/example_2")

    def test_action_panel_layout_and_blur_spinbox(self):
        panel = ActionPanel()
        self.assertTrue(hasattr(panel, "blur_spinbox"))
        self.assertTrue(hasattr(panel, "hide_secure_cb"))
        self.assertTrue(hasattr(panel, "drag_icon"))
        self.assertTrue(hasattr(panel, "keep_downloads_cb"))

        self.assertEqual(panel.blur_spinbox.minimum(), 1)
        self.assertEqual(panel.blur_spinbox.maximum(), 255)
        self.assertEqual(panel.blur_spinbox.value(), config.BLUR_LEVEL)

        # Test value change
        panel.blur_spinbox.setValue(30)
        self.assertEqual(config.BLUR_LEVEL, 30)

    def test_queue_panel_progress_bar(self):
        panel = QueuePanel()
        self.assertTrue(hasattr(panel, "progress"))
        panel.set_progress(50)
        self.assertEqual(panel.progress.value(), 50)

if __name__ == "__main__":
    unittest.main()
