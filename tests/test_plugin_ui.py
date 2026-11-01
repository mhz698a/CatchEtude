"""
UI unit tests for PluginManagerDialog and PluginSettingsDialog.
"""

import sys
import tempfile
import unittest
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QDialog

from localization import LocalizationManager
from plugin_api import PluginState
from plugin_manager import PluginManager
from plugin_manager_dialog import PluginManagerDialog, PluginSettingsDialog


class TestPluginManagerUI(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication(sys.argv)
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.plugins_dir = self.test_dir / "plugins"
        self.plugins_dir.mkdir()

        self.loc = LocalizationManager()
        self.mgr = PluginManager(plugins_dir=self.plugins_dir)

    def test_dialog_instantiation_and_table(self):
        dlg = PluginManagerDialog(self.mgr, self.loc)
        self.assertIsNotNone(dlg.table)
        self.assertEqual(dlg.table.columnCount(), 7)
        dlg.close()

    def test_settings_dialog_fields(self):
        schema = {
            "enabled": {"type": "boolean", "default": True},
            "count": {"type": "integer", "default": 5},
            "ratio": {"type": "number", "default": 1.5},
            "name": {"type": "string", "default": "hello"},
        }
        cfg = {"enabled": False, "count": 10, "ratio": 2.5, "name": "world"}
        dlg = PluginSettingsDialog("test.plugin", schema, cfg, self.loc)

        vals = dlg.get_values()
        self.assertFalse(vals["enabled"])
        self.assertEqual(vals["count"], 10)
        self.assertEqual(vals["ratio"], 2.5)
        self.assertEqual(vals["name"], "world")
        dlg.close()


if __name__ == "__main__":
    unittest.main()
