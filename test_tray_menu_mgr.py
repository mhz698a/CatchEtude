"""
Unit tests for TrayMenuManager.
"""

import unittest
from unittest.mock import MagicMock, patch
import sys


class TestTrayMenuManager(unittest.TestCase):
    def setUp(self):
        # Create mocks for PyQt6 modules to allow testing in headless environments without PyQt6
        self.qt_widgets_mock = MagicMock()
        self.qt_gui_mock = MagicMock()

        self.modules_patcher = patch.dict(
            "sys.modules",
            {
                "PyQt6": MagicMock(),
                "PyQt6.QtWidgets": self.qt_widgets_mock,
                "PyQt6.QtGui": self.qt_gui_mock,
            },
        )
        self.modules_patcher.start()

        # Import TrayMenuManager after mocking PyQt6
        if "tray_menu_mgr" in sys.modules:
            del sys.modules["tray_menu_mgr"]
        import tray_menu_mgr

        self.tray_menu_mgr_module = tray_menu_mgr

    def tearDown(self):
        self.modules_patcher.stop()

    def test_update_show_hide_action_visible(self):
        mw_mock = MagicMock()
        mw_mock.isVisible.return_value = True
        mw_mock.loc.get.side_effect = lambda k: "Ocultar" if k == "tray_hide" else "Mostrar"

        mgr = self.tray_menu_mgr_module.TrayMenuManager(mw_mock)
        mgr.toggle_show_hide_action = MagicMock()

        mgr.update_show_hide_action()
        mgr.toggle_show_hide_action.setText.assert_called_once_with("Ocultar")

    def test_update_show_hide_action_hidden(self):
        mw_mock = MagicMock()
        mw_mock.isVisible.return_value = False
        mw_mock.loc.get.side_effect = lambda k: "Ocultar" if k == "tray_hide" else "Mostrar"

        mgr = self.tray_menu_mgr_module.TrayMenuManager(mw_mock)
        mgr.toggle_show_hide_action = MagicMock()

        mgr.update_show_hide_action()
        mgr.toggle_show_hide_action.setText.assert_called_once_with("Mostrar")

    def test_build_tray(self):
        mw_mock = MagicMock()
        mw_mock.isVisible.return_value = True
        mw_mock.loc.get.return_value = "Text"
        mw_mock.background_move_mgr._history.get_last_move.return_value = None

        mgr = self.tray_menu_mgr_module.TrayMenuManager(mw_mock)

        with patch.object(mgr, "_build_or_update_plugins_submenu"):
            mgr.build_tray()

        self.assertIsNotNone(mgr.tray)
        self.assertIsNotNone(mgr.tray_menu)
        mgr.tray.setContextMenu.assert_called_once_with(mgr.tray_menu)
        mgr.tray.show.assert_called_once()

    def test_on_plugin_tray_action(self):
        mw_mock = MagicMock()
        mgr = self.tray_menu_mgr_module.TrayMenuManager(mw_mock)

        plugin_mgr_mock = MagicMock()
        with patch.dict("sys.modules", {"__main__": MagicMock(plugin_mgr=plugin_mgr_mock)}):
            mgr._on_plugin_tray_action("plugin.id", "do_something")
            plugin_mgr_mock.invoke_command.assert_called_once_with("plugin.id", "do_something")


if __name__ == "__main__":
    unittest.main()
