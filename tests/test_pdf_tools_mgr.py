"""Regression tests for the PDF-specific conversion engine stored in plugins/."""

import importlib.util
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

from PIL import Image
import pymupdf


PDF_MANAGER_PATH = Path(__file__).parent / "plugins" / "pdf_tools_mgr.pylib"
PDF_MANAGER_NAME = "catchetude_test_pdf_tools_mgr"
PDF_MANAGER_SPEC = importlib.util.spec_from_loader(
    PDF_MANAGER_NAME, SourceFileLoader(PDF_MANAGER_NAME, str(PDF_MANAGER_PATH))
)
pdf_tools_mgr = importlib.util.module_from_spec(PDF_MANAGER_SPEC)
PDF_MANAGER_SPEC.loader.exec_module(pdf_tools_mgr)


class TestPdfToolsManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.image_path = self.root / "source.png"
        Image.new("RGB", (64, 48), (20, 90, 160)).save(self.image_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_images_to_pdf_and_pdf_to_jpeg(self):
        events = []
        pdf_path = pdf_tools_mgr.images_to_pdf(
            [self.image_path], self.output,
            progress_cb=lambda *event: events.append(event),
        )
        with pymupdf.open(pdf_path) as document:
            self.assertEqual(len(document), 1)

        generated = pdf_tools_mgr.pdf_to_jpeg(
            [pdf_path], self.output,
            progress_cb=lambda *event: events.append(event),
        )
        self.assertEqual(len(generated), 1)
        self.assertEqual(generated[0].suffix, ".jpeg")
        self.assertTrue(generated[0].is_file())
        self.assertTrue(any("Renderizando" in str(event) for event in events))

    def test_extract_images_from_image_based_pdf(self):
        pdf_path = pdf_tools_mgr.images_to_pdf([self.image_path], self.output)
        generated, warnings = pdf_tools_mgr.extract_pdf_images([pdf_path], self.output)
        self.assertFalse(warnings)
        self.assertGreaterEqual(len(generated), 1)
        self.assertTrue(all(path.is_file() for path in generated))

    def test_merge_pdfs_keeps_every_input_page(self):
        first = pdf_tools_mgr.images_to_pdf([self.image_path], self.output)
        second = pdf_tools_mgr.images_to_pdf([self.image_path], self.output)
        merged = pdf_tools_mgr.merge_pdfs([first, second], self.output)
        with pymupdf.open(merged) as document:
            self.assertEqual(len(document), 2)

    def test_pdf_page_outputs_do_not_overwrite_same_named_inputs(self):
        source_a = self.root / "a"
        source_b = self.root / "b"
        source_a.mkdir()
        source_b.mkdir()
        first = pdf_tools_mgr.images_to_pdf([self.image_path], source_a)
        second = pdf_tools_mgr.images_to_pdf([self.image_path], source_b)
        # Use two PDFs with the same stem to ensure duplicate page names are resolved.
        duplicate_a = source_a / "duplicate.pdf"
        duplicate_b = source_b / "duplicate.pdf"
        first.rename(duplicate_a)
        second.rename(duplicate_b)
        generated = pdf_tools_mgr.pdf_to_jpeg([duplicate_a, duplicate_b], self.output)
        self.assertEqual(len(generated), 2)
        self.assertEqual(len({path.name for path in generated}), 2)


if __name__ == "__main__":
    unittest.main()
