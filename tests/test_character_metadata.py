"""Tests for permissive second-line folder metadata parsing."""
import unittest

from character_metadata import (
    format_character_metadata_line,
    parse_character_folder_metadata,
)


class TestCharacterFolderMetadata(unittest.TestCase):
    def test_non_character_folder_uses_its_name_as_fallback(self):
        self.assertEqual(
            format_character_metadata_line("Research documents", 2025),
            "2025 · Research documents",
        )

    def test_character_metadata_format_is_preserved(self):
        self.assertEqual(
            format_character_metadata_line(
                "22. 03;Alter;Name;1990-04-05;18",
                2025,
            ),
            "2025 · 03 · Name/Alter · 1990-04-05",
        )

    def test_invalid_birthday_does_not_break_metadata(self):
        metadata = parse_character_folder_metadata(
            "22. 07;Alias;Display name;not-a-date;21"
        )
        self.assertEqual(metadata["num"], 7)
        self.assertEqual(metadata["alter"], "Alias")
        self.assertEqual(metadata["name"], "Display name")
        self.assertEqual(metadata["birthday_iso"], "1970-01-01")
        self.assertEqual(metadata["origin_age"], 21)
        self.assertEqual(
            format_character_metadata_line(
                "22. 07;Alias;Display name;not-a-date;21",
                2025,
            ),
            "2025 · 07 · Display name/Alias",
        )

    def test_malformed_or_empty_names_remain_safe(self):
        self.assertEqual(
            format_character_metadata_line("22. ; ; ; ;invalid", 2025),
            "2025 · 22. ; ; ; ;invalid",
        )
        self.assertEqual(format_character_metadata_line("", 2025), "2025 · ")


if __name__ == "__main__":
    unittest.main()
