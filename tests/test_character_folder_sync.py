"""Tests for folder-only synchronization across character-metadata decisions."""
import json
import tempfile
import unittest
from pathlib import Path

import config
from classification_registry import ClassificationRegistry
from decision_dispatcher import DecisionDispatcher
from character_folder_sync import (
    get_character_metadata_decisions,
    sync_character_folder_to_others,
    sync_renamed_character_folder,
)


class TestCharacterFolderSync(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.internal = self.root / "Internal"
        self.internal.mkdir()
        self.config_path = self.root / "classifications.json"

        self.original = {
            key: getattr(config, key)
            for key in (
                "CLASSIFICATIONS_JSON_PATH",
                "BASE_INTERNAL",
                "ONEDRIVE_DOCS",
                "ONEDRIVE_DOCTOS_FAMILIA",
                "IMAGES_FOLDER",
                "MUSIC_FOLDER",
                "OVERWORLD_FOLDER",
                "ACROBAT_FOLDER",
            )
        }
        config.CLASSIFICATIONS_JSON_PATH = self.config_path
        config.BASE_INTERNAL = self.internal
        config.ONEDRIVE_DOCS = self.root / "Documents"
        config.ONEDRIVE_DOCTOS_FAMILIA = self.root / "Family"
        config.IMAGES_FOLDER = "Images"
        config.MUSIC_FOLDER = "Music"
        config.OVERWORLD_FOLDER = "Overworld"
        config.ACROBAT_FOLDER = "PDF"

    def tearDown(self):
        for key, value in self.original.items():
            setattr(config, key, value)
        self.temp.cleanup()

    def _registry(self, *decisions):
        self.config_path.write_text(
            json.dumps({"schema_version": 2, "decisions": list(decisions)}),
            encoding="utf-8",
        )
        registry = ClassificationRegistry(self.config_path)
        return registry, DecisionDispatcher(registry=registry)

    @staticmethod
    def _decision(decision_id, folder_name, *, enabled=True, second_line="character_metadata"):
        return {
            "id": decision_id,
            "name": f"Decision {decision_id}",
            "enabled": enabled,
            "order": decision_id,
            "handler": "move_to_subfolder",
            "year_mode": "required",
            "base_path": f"{{BASE_INTERNAL}}/{{year}}/{folder_name}",
            "folder_source": "filesystem",
            "behaviour_second_line": second_line,
            "requires_internal": False,
            "allow_create": True,
            "allow_rename": True,
            "allow_delete": True,
        }

    def test_sync_creates_empty_folder_without_copying_source_contents(self):
        registry, dispatcher = self._registry(
            self._decision(20, "Characters"),
            self._decision(21, "Reference"),
            self._decision(22, "Archive", enabled=False),
            self._decision(23, "Episodes", second_line="last_file"),
        )
        source_base = self.internal / "2025" / "Characters"
        source_folder = source_base / "Mira"
        source_folder.mkdir(parents=True)
        (source_folder / "portrait.png").write_bytes(b"source data")

        report = sync_character_folder_to_others(
            registry, dispatcher, 2025, "Mira", 20, source_base
        )

        reference = self.internal / "2025" / "Reference" / "Mira"
        archive = self.internal / "2025" / "Archive" / "Mira"
        self.assertEqual(report.created, [reference, archive])
        self.assertEqual(report.failed_count, 0)
        self.assertTrue(source_folder.joinpath("portrait.png").is_file())
        self.assertTrue(reference.is_dir())
        self.assertTrue(archive.is_dir())
        self.assertEqual(list(reference.iterdir()), [])
        self.assertEqual(list(archive.iterdir()), [])
        self.assertFalse((self.internal / "2025" / "Episodes" / "Mira").exists())

    def test_sync_leaves_existing_folder_and_contents_untouched(self):
        registry, dispatcher = self._registry(
            self._decision(20, "Characters"),
            self._decision(21, "Reference"),
        )
        source_base = self.internal / "2025" / "Characters"
        reference_folder = self.internal / "2025" / "Reference" / "Mira"
        source_base.mkdir(parents=True)
        reference_folder.mkdir(parents=True)
        existing_file = reference_folder / "reference.txt"
        existing_file.write_text("keep", encoding="utf-8")

        report = sync_character_folder_to_others(
            registry, dispatcher, 2025, "Mira", 20, source_base
        )

        self.assertEqual(report.created, [])
        self.assertEqual(report.existing, [reference_folder])
        self.assertEqual(existing_file.read_text(encoding="utf-8"), "keep")

    def test_rename_propagates_existing_folder_and_creates_missing_counterpart(self):
        registry, dispatcher = self._registry(
            self._decision(20, "Characters"),
            self._decision(21, "Reference"),
            self._decision(22, "Archive"),
        )
        source_base = self.internal / "2025" / "Characters"
        source_base.mkdir(parents=True)
        (source_base / "Mira Renamed").mkdir()

        reference_old = self.internal / "2025" / "Reference" / "Mira"
        reference_old.mkdir(parents=True)
        retained = reference_old / "reference.txt"
        retained.write_text("reference data", encoding="utf-8")

        archive_base = self.internal / "2025" / "Archive"
        report = sync_renamed_character_folder(
            registry,
            dispatcher,
            2025,
            "Mira",
            "Mira Renamed",
            20,
            source_base,
        )

        reference_new = reference_old.with_name("Mira Renamed")
        archive_new = archive_base / "Mira Renamed"
        self.assertEqual(report.renamed, [(reference_old, reference_new)])
        self.assertEqual(report.created, [archive_new])
        self.assertEqual(report.failed_count, 0)
        self.assertFalse(reference_old.exists())
        self.assertEqual((reference_new / "reference.txt").read_text(encoding="utf-8"), "reference data")
        self.assertEqual(list(archive_new.iterdir()), [])

    def test_rename_does_not_overwrite_when_old_and_new_both_exist(self):
        registry, dispatcher = self._registry(
            self._decision(20, "Characters"),
            self._decision(21, "Reference"),
        )
        source_base = self.internal / "2025" / "Characters"
        source_base.mkdir(parents=True)
        reference_base = self.internal / "2025" / "Reference"
        old_folder = reference_base / "Mira"
        new_folder = reference_base / "Mira Renamed"
        old_folder.mkdir(parents=True)
        new_folder.mkdir(parents=True)
        old_file = old_folder / "old.txt"
        new_file = new_folder / "new.txt"
        old_file.write_text("old", encoding="utf-8")
        new_file.write_text("new", encoding="utf-8")

        report = sync_renamed_character_folder(
            registry,
            dispatcher,
            2025,
            "Mira",
            "Mira Renamed",
            20,
            source_base,
        )

        self.assertEqual(report.renamed, [])
        self.assertEqual(report.created, [])
        self.assertEqual(report.failed_count, 1)
        self.assertTrue(old_file.exists())
        self.assertTrue(new_file.exists())

    def test_invalid_folder_names_are_rejected_before_sync(self):
        registry, dispatcher = self._registry(
            self._decision(20, "Characters"),
            self._decision(21, "Reference"),
        )
        source_base = self.internal / "2025" / "Characters"

        for name in ("", ".", "..", "../escape", "folder/name", "folder\\name"):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    sync_character_folder_to_others(
                        registry, dispatcher, 2025, name, 20, source_base
                    )

        self.assertFalse((self.root / "escape").exists())

    def test_metadata_decision_discovery_includes_disabled_definitions_only(self):
        registry, _ = self._registry(
            self._decision(20, "Characters"),
            self._decision(21, "Reference", enabled=False),
            self._decision(22, "Episodes", second_line="last_file"),
        )

        self.assertEqual(
            [decision["id"] for decision in get_character_metadata_decisions(registry)],
            [20, 21],
        )


if __name__ == "__main__":
    unittest.main()
