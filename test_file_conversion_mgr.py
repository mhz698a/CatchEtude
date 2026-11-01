"""Tests for the image, SVG, and dispatch helpers in file_conversion_mgr."""

import os
import sys
import tempfile
import types
import importlib.util
from importlib.machinery import SourceFileLoader
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PyQt6.QtWidgets import QApplication
from mutagen.id3 import ID3, TIT2, TXXX

_APP = QApplication.instance() or QApplication([])

_CONVERSION_PATH = Path(__file__).parent / "plugins" / "file_conversion_mgr.pylib"
_CONVERSION_NAME = "catchetude_test_file_conversion_mgr"
_CONVERSION_SPEC = importlib.util.spec_from_loader(
    _CONVERSION_NAME, SourceFileLoader(_CONVERSION_NAME, str(_CONVERSION_PATH))
)
file_conversion_mgr = importlib.util.module_from_spec(_CONVERSION_SPEC)
sys.modules[_CONVERSION_NAME] = file_conversion_mgr
_CONVERSION_SPEC.loader.exec_module(file_conversion_mgr)


class TestFileConversionManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output = self.root / "output"
        self.output.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _create_png(self, name="sample.png"):
        path = self.root / name
        Image.new("RGBA", (40, 24), (255, 0, 0, 128)).save(path)
        return path

    def test_heif_and_avif_formats_are_registered(self):
        extensions = Image.registered_extensions()
        self.assertIn(".heic", extensions)
        self.assertIn(".heif", extensions)
        self.assertIn(".avif", extensions)

    def test_raster_conversions_generate_ico_png_and_jpg(self):
        source = self._create_png()
        ico_files, ico_warnings = file_conversion_mgr.images_to_ico([source], self.output)
        png_files, png_warnings = file_conversion_mgr.images_to_png([source], self.output)
        jpg_files, jpg_warnings = file_conversion_mgr.images_to_jpg([source], self.output)

        self.assertFalse(ico_warnings)
        self.assertFalse(png_warnings)
        self.assertFalse(jpg_warnings)
        self.assertEqual(ico_files[0].suffix, ".ico")
        self.assertEqual(png_files[0].suffix, ".png")
        self.assertEqual(jpg_files[0].suffix, ".jpg")
        self.assertTrue(all(path.exists() for path in ico_files + png_files + jpg_files))

    def test_ico_keeps_original_dimensions_without_small_variants(self):
        source = self._create_png()
        ico_files, warnings = file_conversion_mgr.images_to_ico([source], self.output)

        self.assertFalse(warnings)
        with Image.open(ico_files[0]) as converted:
            self.assertEqual(converted.size, (40, 24))
            self.assertEqual(converted.ico.sizes(), {(40, 24)})

    def test_ico_caps_large_images_at_256_preserving_aspect_ratio(self):
        source = self.root / "large.png"
        Image.new("RGBA", (512, 300), (0, 128, 255, 255)).save(source)

        ico_files, warnings = file_conversion_mgr.images_to_ico([source], self.output)

        self.assertFalse(warnings)
        with Image.open(ico_files[0]) as converted:
            self.assertEqual(converted.size, (256, 150))
            self.assertEqual(converted.ico.sizes(), {(256, 150)})

    def test_raster_conversions_avoid_name_collisions(self):
        source = self._create_png()
        first, _ = file_conversion_mgr.images_to_png([source], self.output)
        second, _ = file_conversion_mgr.images_to_png([source], self.output)

        self.assertEqual(first[0].name, "sample.png")
        self.assertEqual(second[0].name, "sample_001.png")

    def test_svg_conversions_generate_png_and_ico(self):
        source = self.root / "vector.svg"
        source.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32">'
            '<rect width="32" height="32" fill="#336699"/></svg>',
            encoding="utf-8",
        )
        png_files, png_warnings = file_conversion_mgr.svgs_to_png([source], self.output)
        ico_files, ico_warnings = file_conversion_mgr.svgs_to_ico([source], self.output)

        self.assertFalse(png_warnings)
        self.assertFalse(ico_warnings)
        self.assertEqual(png_files[0].suffix, ".png")
        self.assertEqual(ico_files[0].suffix, ".ico")
        self.assertTrue(png_files[0].exists())
        self.assertTrue(ico_files[0].exists())

    def test_mp3_tag_copy_preserves_standard_and_custom_id3_frames(self):
        source = self.root / "source.flac"
        output = self.output / "result.mp3"
        source.write_bytes(b"source")
        output.write_bytes(b"audio-data")

        source_tags = ID3()
        source_tags.add(TIT2(encoding=3, text=["Original title"]))
        source_tags.add(TXXX(encoding=3, desc="CUSTOM_FIELD", text=["custom value"]))
        fake_audio = types.SimpleNamespace(tags=source_tags)

        with patch("mutagen.File", return_value=fake_audio):
            file_conversion_mgr._copy_audio_tags(source, output)

        copied = ID3(str(output))
        self.assertEqual(copied["TIT2"].text, ["Original title"])
        custom_frames = copied.getall("TXXX")
        self.assertTrue(any(
            frame.desc == "CUSTOM_FIELD" and frame.text == ["custom value"]
            for frame in custom_frames
        ))

    def test_word_conversion_uses_word_com_and_outputs_pdf(self):
        source = self.root / "document.docx"
        source.write_bytes(b"word document")

        progress_events = []
        document = types.SimpleNamespace()
        document.SaveAs2 = lambda path, FileFormat: Path(path).write_bytes(b"%PDF")
        document.Close = Mock()
        documents = types.SimpleNamespace(Open=Mock(return_value=document))
        word = types.SimpleNamespace(
            Visible=True,
            DisplayAlerts=1,
            Documents=documents,
            Quit=Mock(),
        )

        pythoncom = types.ModuleType("pythoncom")
        pythoncom.CoInitialize = Mock()
        pythoncom.CoUninitialize = Mock()
        client = types.ModuleType("win32com.client")
        client.DispatchEx = Mock(return_value=word)
        win32com = types.ModuleType("win32com")
        win32com.__path__ = []
        win32com.client = client

        with patch.dict(sys.modules, {
            "pythoncom": pythoncom,
            "win32com": win32com,
            "win32com.client": client,
        }):
            generated, warnings = file_conversion_mgr.words_to_pdf(
                [source], self.output,
                progress_cb=lambda cur, total, message, busy: progress_events.append((message, busy)),
            )

        self.assertFalse(warnings)
        self.assertEqual(generated[0].suffix, ".pdf")
        self.assertEqual(generated[0].read_bytes(), b"%PDF")
        client.DispatchEx.assert_called_once_with("Word.Application")
        document.Close.assert_called_once()
        self.assertTrue(any("Microsoft Word está exportando" in message and busy for message, busy in progress_events))
        self.assertTrue(any("PDF generado" in message and not busy for message, busy in progress_events))
    def test_dispatch_rejects_unknown_task(self):
        with self.assertRaises(ValueError):
            file_conversion_mgr.run_file_conversion("unknown", [], self.output)


if __name__ == "__main__":
    unittest.main()
