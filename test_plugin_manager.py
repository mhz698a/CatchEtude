"""Tests for hot plugin enable/disable and tray action exposure."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QCoreApplication

from plugin_api import PluginState
from plugin_host import PluginProcess
from plugin_manager import PluginManager


PLUGIN_SOURCE = """# /// catch-etude-plugin
# [plugin]
# id = "test.live-plugin"
# name = "Live Plugin"
# version = "1.0.0"
# api_version = 1
# capabilities = ["tray_action"]
# events = []
# [[tray_actions]]
# id = "run"
# label = "Run now"
# command = "run"
# group = "Runtime"
# /// end catch-etude-plugin
"""


class TestPluginManagerHotLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.plugins_dir = self.temp_dir / "plugins"
        self.plugins_dir.mkdir()
        (self.plugins_dir / "live_plugin.py").write_text(
            PLUGIN_SOURCE, encoding="utf-8"
        )

        self.manager = PluginManager(plugins_dir=self.plugins_dir)
        self.manager.registry.state_path = self.temp_dir / "plugins-state.json"
        self.manager.registry.config_dir = self.temp_dir / "plugins-config"
        self.manager.registry.config_dir.mkdir()

    def tearDown(self):
        self.manager.shutdown()
        for child in self.temp_dir.rglob("*"):
            if child.is_file():
                child.unlink()
        for child in sorted(self.temp_dir.rglob("*"), reverse=True):
            if child.is_dir():
                child.rmdir()
        self.temp_dir.rmdir()

    def test_enable_starts_plugin_without_rebuilding_manager(self):
        self.manager.discover()
        proc = self.manager.processes["test.live-plugin"]

        with patch.object(PluginProcess, "start") as start_mock:
            self.assertTrue(self.manager.enable_plugin("test.live-plugin"))

        start_mock.assert_called_once_with()
        self.assertTrue(proc.plugin.is_enabled)
        self.assertIs(
            self.manager.registry.plugins_by_id["test.live-plugin"],
            proc.plugin,
        )
        self.assertEqual(proc.plugin.state, PluginState.DISCOVERED)

    def test_disable_stops_plugin_and_removes_tray_actions(self):
        self.manager.discover()
        proc = self.manager.processes["test.live-plugin"]
        self.assertTrue(self.manager.registry.set_enabled("test.live-plugin", True))
        proc.plugin.state = PluginState.RUNNING
        self.assertEqual(len(self.manager.get_tray_actions()), 1)

        with patch.object(proc, "stop") as stop_mock:
            self.assertTrue(self.manager.disable_plugin("test.live-plugin"))

        stop_mock.assert_called_once_with()
        self.assertFalse(proc.plugin.is_enabled)
        self.assertEqual(proc.plugin.state, PluginState.DISABLED)
        self.assertEqual(self.manager.get_tray_actions(), [])


if __name__ == "__main__":
    unittest.main()
