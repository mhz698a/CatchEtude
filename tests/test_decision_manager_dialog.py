"""Offscreen smoke tests for the visual classification manager."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from classification_registry import ClassificationRegistry
from decision_manager_dialog import DecisionManagerDialog
from localization import STRINGS


class TestLocalization:
    def current_lang(self):
        return "es"

    def get(self, key):
        return STRINGS.get("es", {}).get(key, key)


class TestDecisionManagerDialog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_path = self.root / "classifications.json"
        self.registry = ClassificationRegistry(self.config_path)
        self.dialog = DecisionManagerDialog(self.registry, TestLocalization())

    def tearDown(self):
        self.dialog.close()
        self.temp.cleanup()

    def _row_for_id(self, decision_id):
        for row in range(self.dialog.list_widget.count()):
            item = self.dialog.list_widget.item(row)
            if item.data(self.dialog.list_widget.model().index(row, 0).data.__self__.UserRole) == decision_id:
                return row
        raise AssertionError(f"Classification {decision_id} was not listed")

    def test_dialog_loads_classifications_and_protects_keep(self):
        self.assertEqual(self.dialog.list_widget.count(), len(self.registry.decisions))
        self.dialog.list_widget.setCurrentRow(self._row_for_id(1))
        self.assertFalse(self.dialog.btn_remove.isEnabled())
        self.assertFalse(self.dialog.btn_duplicate.isEnabled())
        self.assertEqual(self.dialog.handler_value.text(), self.dialog._handler_label("keep"))

    def test_edits_are_saved_to_registry_and_json(self):
        self.dialog.list_widget.setCurrentRow(self._row_for_id(3))
        self.dialog.name_edit.setText("Series")
        self.dialog._save()

        updated = self.registry.get_decision(3)
        self.assertEqual(updated["name"]["es"], "Series")
        stored = json.loads(self.config_path.read_text(encoding="utf-8"))
        saved = next(item for item in stored["decisions"] if item["id"] == 3)
        self.assertEqual(saved["name"]["es"], "Series")
        self.assertEqual(saved["behaviour_second_line"], "last_file")

    def test_path_preview_does_not_create_directories(self):
        self.dialog.list_widget.setCurrentRow(self._row_for_id(3))
        preview_path = self.root / "must-not-be-created"
        self.dialog.base_path_edit.setText(str(preview_path))
        self.dialog.folder_source_combo.setCurrentIndex(
            self.dialog.folder_source_combo.findData("none")
        )
        self.dialog._preview_path()

        self.assertFalse(preview_path.exists())
        self.assertIn(str(preview_path), self.dialog.preview_label.text())

    def test_empty_name_blocks_saving(self):
        self.dialog.list_widget.setCurrentRow(self._row_for_id(3))
        original = self.registry.get_decision(3)
        self.dialog.name_edit.clear()

        with patch.object(QtWidgets.QMessageBox, "warning") as warning:
            self.dialog._save()

        self.assertTrue(warning.called)
        self.assertEqual(self.registry.get_decision(3), original)
        self.assertEqual(self.dialog.result(), 0)

    def test_external_config_change_is_not_overwritten(self):
        self.dialog.list_widget.setCurrentRow(self._row_for_id(3))
        self.dialog.name_edit.setText("Local edit")

        external = json.loads(self.config_path.read_text(encoding="utf-8"))
        external["external_marker"] = "preserve"
        self.config_path.write_text(
            json.dumps(external, ensure_ascii=False), encoding="utf-8"
        )
        external_bytes = self.config_path.read_bytes()

        with patch.object(QtWidgets.QMessageBox, "critical") as critical:
            self.dialog._save()

        self.assertTrue(critical.called)
        self.assertEqual(self.config_path.read_bytes(), external_bytes)
        self.assertEqual(
            json.loads(self.config_path.read_text(encoding="utf-8"))["external_marker"],
            "preserve",
        )
        self.assertNotEqual(
            self.registry.get_decision(3).get("name"),
            {"es": "Local edit", "en": "Episodes"},
        )

    def test_switching_classifications_commits_pending_editor_changes(self):
        self.dialog.list_widget.setCurrentRow(self._row_for_id(3))
        self.dialog.name_edit.setText("Episodios alternativos")
        self.dialog.list_widget.setCurrentRow(self._row_for_id(4))

        edited = self.dialog.model.get_decision(3)
        self.assertEqual(edited["name"]["es"], "Episodios alternativos")
        self.assertEqual(self.dialog._current_id(), 4)


if __name__ == "__main__":
    unittest.main()
