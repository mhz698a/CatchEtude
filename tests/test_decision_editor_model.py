"""Unit tests for the non-Qt classification editor model."""
import copy
import unittest

from classification_registry import ClassificationRegistry, DEFAULT_DECISIONS
from decision_editor_model import (
    DecisionEditorModel,
    validate_decision_configuration,
)


class TestDecisionEditorModel(unittest.TestCase):
    def setUp(self):
        self.original = copy.deepcopy(DEFAULT_DECISIONS)
        self.model = DecisionEditorModel(self.original)

    def test_add_assigns_new_monotonic_id_and_valid_default_definition(self):
        new_id = self.model.add("Archivos personales")
        decisions = self.model.snapshot()
        created = next(item for item in decisions if item["id"] == new_id)

        self.assertEqual(new_id, 9)
        self.assertEqual(created["handler"], "move_to_subfolder")
        self.assertEqual(created["base_path"], "{BASE_INTERNAL}")
        self.assertEqual(created["folder_source"], "filesystem")
        self.assertEqual(created["order"], len(decisions))
        ClassificationRegistry.validate_decisions(decisions)

    def test_duplicate_is_independent_and_inserted_after_source(self):
        new_id = self.model.duplicate(3, "Copia de Episodios")
        decisions = self.model.snapshot()
        ids = [item["id"] for item in decisions]
        duplicate = next(item for item in decisions if item["id"] == new_id)

        self.assertEqual(new_id, 9)
        self.assertEqual(ids[2:4], [3, 9])
        self.assertEqual(duplicate["name"], "Copia de Episodios")
        self.assertEqual(duplicate["folder_contains"], "___[")
        self.assertEqual(duplicate["behaviour_second_line"], "last_file")
        self.assertEqual(
            next(item for item in self.original if item["id"] == 3)["name_key"],
            "type_3",
        )
        ClassificationRegistry.validate_decisions(decisions)

    def test_keep_cannot_be_deleted_or_duplicated(self):
        with self.assertRaisesRegex(ValueError, "Keep"):
            self.model.delete(1)
        with self.assertRaisesRegex(ValueError, "Keep"):
            self.model.duplicate(1, "Copia de Keep")
        self.assertIsNotNone(self.model.get_decision(1))

    def test_delete_removes_decision_and_reindexes_order(self):
        self.model.add("Temporal")
        self.model.delete(4)
        decisions = self.model.snapshot()

        self.assertFalse(any(item["id"] == 4 for item in decisions))
        self.assertTrue(any(item["id"] == 9 for item in decisions))
        self.assertEqual(
            [item["order"] for item in decisions],
            list(range(1, len(decisions) + 1)),
        )
        ClassificationRegistry.validate_decisions(decisions)

    def test_enabled_flag_is_modified_without_changing_order(self):
        before = self.model.snapshot()
        self.model.set_enabled(3, False)
        after = self.model.snapshot()
        self.assertFalse(next(item for item in after if item["id"] == 3)["enabled"])
        self.assertEqual(
            [item["order"] for item in before],
            [item["order"] for item in after],
        )

    def test_move_changes_order_but_not_ids(self):
        self.model.move(4, -1)
        decisions = self.model.snapshot()

        self.assertEqual([item["id"] for item in decisions][2:4], [4, 3])
        self.assertEqual(
            [item["order"] for item in decisions],
            list(range(1, len(decisions) + 1)),
        )
        self.assertEqual(
            {item["id"] for item in decisions},
            {item["id"] for item in self.original},
        )

    def test_update_fields_changes_route_and_behavior(self):
        self.model.update_fields(3, {
            "name": "Series",
            "base_path": "{BASE_INTERNAL}/{year}",
            "folder_contains": "___[",
            "folder_fallback": "{BASE_INTERNAL}/{year}",
            "behaviour_second_line": "last_file",
        })
        episode = self.model.get_decision(3)
        self.assertEqual(episode["name"], "Series")
        self.assertEqual(episode["folder_contains"], "___[")
        self.assertEqual(episode["behaviour_second_line"], "last_file")
        validate_decision_configuration(episode)

    def test_update_fields_can_clear_optional_folder_rules(self):
        self.model.update_fields(3, {
            "folder_contains": None,
            "folder_fallback": None,
            "behaviour_second_line": None,
        })
        episode = self.model.get_decision(3)
        self.assertNotIn("folder_contains", episode)
        self.assertNotIn("folder_fallback", episode)
        self.assertNotIn("behaviour_second_line", episode)
        validate_decision_configuration(episode)

    def test_all_builtin_decisions_pass_editor_validation(self):
        for decision in DEFAULT_DECISIONS:
            with self.subTest(decision_id=decision["id"]):
                validate_decision_configuration(decision)

    def test_localized_names_are_valid(self):
        episode = copy.deepcopy(self.model.get_decision(3))
        episode["name"] = {"es": "Episodios", "en": "Episodes"}
        validate_decision_configuration(episode)

    def test_year_placeholder_requires_year_mode(self):
        episode = copy.deepcopy(self.model.get_decision(3))
        episode["year_mode"] = "none"
        with self.assertRaisesRegex(ValueError, "year variables require"):
            validate_decision_configuration(episode)

    def test_unknown_path_placeholder_is_rejected(self):
        episode = copy.deepcopy(self.model.get_decision(3))
        episode["base_path"] = "{BASE_INTERNAL}/{unknown_value}"
        with self.assertRaisesRegex(ValueError, "unknown path variable"):
            validate_decision_configuration(episode)

    def test_folder_fallback_requires_folder_contains(self):
        episode = copy.deepcopy(self.model.get_decision(3))
        episode.pop("folder_contains", None)
        episode["folder_fallback"] = "{BASE_INTERNAL}/{year}"
        with self.assertRaisesRegex(ValueError, "fallback requires"):
            validate_decision_configuration(episode)

    def test_linear_docs_must_keep_year_selection(self):
        linear = copy.deepcopy(self.model.get_decision(7))
        linear["year_mode"] = "none"
        with self.assertRaisesRegex(ValueError, "requires year selection"):
            validate_decision_configuration(linear)

    def test_model_does_not_mutate_registry_input(self):
        self.model.add("No debe modificar el original")
        self.assertEqual(self.original, DEFAULT_DECISIONS)


if __name__ == "__main__":
    unittest.main()
