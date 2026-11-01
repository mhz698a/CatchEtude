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

    def test_order_one_pending_precedes_order_pending(self):
        mw_mock = MagicMock()
        mw_mock.isVisible.return_value = True
        mw_mock.loc.get.side_effect = lambda key: key
        mw_mock.background_move_mgr._history.get_last_move.return_value = None

        mgr = self.tray_menu_mgr_module.TrayMenuManager(mw_mock)
        created_actions = []

        def create_action(label, parent=None):
            action = MagicMock()
            action.label = label
            created_actions.append(action)
            return action

        with patch.object(self.tray_menu_mgr_module, "QAction", side_effect=create_action):
            with patch.object(mgr, "_build_or_update_plugins_submenu"):
                mgr.build_tray()

        labels = [action.label for action in created_actions]
        one_pending_index = labels.index("tray_order_one_pending")
        all_pending_index = labels.index("tray_order_pending")
        self.assertEqual(one_pending_index + 1, all_pending_index)

        created_actions[one_pending_index].triggered.connect.assert_called_once_with(
            mw_mock._on_order_one_pending_clicked
        )

    def test_on_plugin_tray_action_uses_main_window_manager(self):
        mw_mock = MagicMock()
        plugin_mgr_mock = MagicMock()
        mw_mock.plugin_mgr = plugin_mgr_mock
        mgr = self.tray_menu_mgr_module.TrayMenuManager(mw_mock)

        mgr._on_plugin_tray_action("plugin.id", "do_something")
        plugin_mgr_mock.invoke_command.assert_called_once_with("plugin.id", "do_something")

    def test_plugin_tray_actions_are_read_from_main_window_manager(self):
        mw_mock = MagicMock()
        plugin_mgr_mock = MagicMock()
        expected_actions = [
            {
                "plugin_id": "plugin.id",
                "label": "Convert",
                "command": "convert",
                "group": "File tools",
            }
        ]
        plugin_mgr_mock.get_tray_actions.return_value = expected_actions
        mw_mock.plugin_mgr = plugin_mgr_mock
        mgr = self.tray_menu_mgr_module.TrayMenuManager(mw_mock)

        self.assertEqual(mgr._get_plugin_tray_actions(), expected_actions)

    def test_plugin_group_is_added_as_tray_submenu(self):
        mw_mock = MagicMock()
        plugin_mgr_mock = MagicMock()
        plugin_mgr_mock.get_tray_actions.return_value = [
            {
                "plugin_id": "plugin.id",
                "label": "Convert",
                "command": "convert",
                "group": "File tools",
            }
        ]
        mw_mock.plugin_mgr = plugin_mgr_mock
        mgr = self.tray_menu_mgr_module.TrayMenuManager(mw_mock)
        mgr.tray_menu = MagicMock()
        group_menu = MagicMock()
        action = MagicMock()

        with patch.object(self.tray_menu_mgr_module, "QMenu", return_value=group_menu):
            with patch.object(self.tray_menu_mgr_module, "QAction", return_value=action):
                mgr._build_or_update_plugins_submenu()

        group_menu.addAction.assert_called_once_with(action)
        mgr.tray_menu.addMenu.assert_called_once_with(group_menu)


if __name__ == "__main__":
    unittest.main()
