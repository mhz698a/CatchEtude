"""Regression tests for plugin actions injected into ActionToolBar."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets
from PyQt6.QtGui import QAction

from action_panel_mgr import ActionPanel


_APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class FakePluginManager:
    def __init__(self, definitions):
        self.definitions = definitions
        self.invocations = []

    def get_ui_action_buttons(self):
        return self.definitions

    def invoke_command(self, plugin_id, command, args):
        self.invocations.append((plugin_id, command, args))
        return True


class TestActionToolbarPluginActions(unittest.TestCase):
    def setUp(self):
        self.previous_plugin_manager = getattr(sys.modules["__main__"], "plugin_mgr", None)
        self.had_plugin_manager = hasattr(sys.modules["__main__"], "plugin_mgr")

    def tearDown(self):
        if self.had_plugin_manager:
            sys.modules["__main__"].plugin_mgr = self.previous_plugin_manager
        else:
            try:
                del sys.modules["__main__"].plugin_mgr
            except AttributeError:
                pass

    def test_plugin_command_is_a_toolbar_action_not_a_push_button(self):
        with tempfile.TemporaryDirectory() as temp:
            file_path = Path(temp) / "example.txt"
            file_path.write_text("data")
            manager = FakePluginManager([{
                "plugin_id": "test.plugin",
                "label": "Process file",
                "target": "file",
                "file_extensions": [".txt"],
                "command": "process",
            }])
            sys.modules["__main__"].plugin_mgr = manager

            panel = ActionPanel()
            panel.filepath = file_path
            panel._update_dynamic_plugin_buttons()

            dynamic_actions = [
                action for action in panel.action_toolbar.actions()
                if action.property("catchEtudeDynamicAction")
            ]
            self.assertEqual(len(dynamic_actions), 1)
            self.assertIsInstance(dynamic_actions[0], QAction)

            action_widget = panel.action_toolbar.widgetForAction(dynamic_actions[0])
            self.assertIsInstance(action_widget, QtWidgets.QToolButton)
            self.assertNotIsInstance(action_widget, QtWidgets.QPushButton)
            self.assertFalse(hasattr(panel, "dynamic_btn_layout"))

            dynamic_actions[0].trigger()
            self.assertEqual(len(manager.invocations), 1)
            self.assertEqual(
                manager.invocations[0],
                ("test.plugin", "process", {"paths": [str(file_path)]}),
            )
            panel.close()

    def test_plugin_menu_is_attached_to_toolbar_action(self):
        with tempfile.TemporaryDirectory() as temp:
            file_path = Path(temp) / "example.txt"
            file_path.write_text("data")
            manager = FakePluginManager([{
                "plugin_id": "test.plugin",
                "label": "Convert",
                "target": "file",
                "menu_items": [
                    {"label": "Convert to PNG", "command": "to_png"},
                    {"label": "Convert to JPG", "command": "to_jpg"},
                ],
            }])
            sys.modules["__main__"].plugin_mgr = manager

            panel = ActionPanel()
            panel.filepath = file_path
            panel._update_dynamic_plugin_buttons()

            dynamic_actions = [
                action for action in panel.action_toolbar.actions()
                if action.property("catchEtudeDynamicAction")
            ]
            self.assertEqual(len(dynamic_actions), 1)
            self.assertIsNotNone(dynamic_actions[0].menu())
            self.assertEqual(
                [action.text() for action in dynamic_actions[0].menu().actions()],
                ["Convert to PNG", "Convert to JPG"],
            )

            dynamic_actions[0].menu().actions()[1].trigger()
            self.assertEqual(
                manager.invocations,
                [("test.plugin", "to_jpg", {"paths": [str(file_path)]})],
            )
            panel.close()

    def test_dynamic_actions_are_removed_when_no_file_is_selected(self):
        panel = ActionPanel()
        panel.filepath = None
        panel.action_toolbar.add_dynamic_action("Temporary plugin action")
        self.assertTrue(any(
            action.property("catchEtudeDynamicAction")
            for action in panel.action_toolbar.actions()
        ))

        panel._update_dynamic_plugin_buttons()
        self.assertFalse(any(
            action.property("catchEtudeDynamicAction")
            for action in panel.action_toolbar.actions()
        ))
        panel.close()


if __name__ == "__main__":
    unittest.main()
