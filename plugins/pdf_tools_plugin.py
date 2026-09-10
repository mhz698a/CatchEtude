# /// catch-etude-plugin
# [plugin]
# id = "catchetude.pdf-tools"
# name = "Herramientas PDF Plugin"
# version = "1.0.3"
# api_version = 1
# capabilities = ["background_task", "tray_action", "ui_action"]
# events = []
#
# [[tray_actions]]
# id = "imgs_to_pdf"
# label = "IMGs a PDF"
# command = "imgs_to_pdf"
# group = "Convertir Archivo"
#
# [[tray_actions]]
# id = "pdf_to_jpeg"
# label = "PDF a JPEG"
# command = "pdf_to_jpeg"
# group = "Convertir Archivo"
#
# [[tray_actions]]
# id = "extract_images"
# label = "Extraer imágenes de PDF"
# command = "extract_images"
# group = "Convertir Archivo"
#
# [[tray_actions]]
# id = "merge_pdfs"
# label = "Unir PDFs"
# command = "merge_pdfs"
# group = "Convertir Archivo"
#
# [[action_buttons]]
# id = "btn_manage_pdf"
# label = "Gestionar PDF"
# file_extensions = [".pdf"]
# menu_items = [
#     { label = "Paginas a JPG", command = "pdf_to_jpeg" },
#     { label = "Extraer imágenes de PDF", command = "extract_images" },
# ]
# /// end catch-etude-plugin

"""
PDF Tools Plugin for CatchEtude.
Provides conversion and image extraction utilities for PDF files.
"""

import importlib.util
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog

import config

# The progress UI is a private plugin resource (.pylib keeps it out of plugin
# discovery, which intentionally scans only executable .py/.pyw plugins).
_runner_path = Path(__file__).with_name("pdf_gui_runner.pylib")
_runner_spec = importlib.util.spec_from_loader(
    "catchetude_pdf_tools_gui_runner", SourceFileLoader("catchetude_pdf_tools_gui_runner", str(_runner_path))
)
if _runner_spec is None or _runner_spec.loader is None:
    raise ImportError(f"Could not load PDF GUI runner: {_runner_path}")
_runner_module = importlib.util.module_from_spec(_runner_spec)
sys.modules[_runner_spec.name] = _runner_module
_runner_spec.loader.exec_module(_runner_module)
run_pdf_task = _runner_module.run_pdf_task


def run_plugin(ctx):
    ctx.log("INFO", "PDF Tools plugin initialized.")

    def selected_paths(args, file_filter, title):
        """Use paths supplied by a contextual UI action, otherwise ask the user."""
        paths = [Path(path) for path in (args or {}).get("paths", [])]
        if paths:
            return paths

        files, _ = QFileDialog.getOpenFileNames(
            None, title, str(config.DOWNLOADS), file_filter
        )
        return [Path(file_path) for file_path in files]

    def on_imgs_to_pdf(args):
        file_filter = "Imágenes (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)"
        paths = selected_paths(args, file_filter, "Seleccionar imágenes")
        if paths:
            run_pdf_task(None, "imgs_to_pdf", paths, "IMGs a PDF")

    def on_pdf_to_jpeg(args):
        file_filter = "Archivos PDF (*.pdf)"
        paths = selected_paths(args, file_filter, "Seleccionar PDFs")
        if paths:
            run_pdf_task(None, "pdf_to_jpeg", paths, "Páginas a JPG")

    def on_extract_images(args):
        file_filter = "Archivos PDF (*.pdf)"
        paths = selected_paths(args, file_filter, "Seleccionar PDFs")
        if paths:
            run_pdf_task(None, "extract_images", paths, "Extraer imágenes de PDF")

    def on_merge_pdfs(args):
        file_filter = "Archivos PDF (*.pdf)"
        paths = selected_paths(args, file_filter, "Seleccionar PDFs")
        if paths:
            run_pdf_task(None, "merge_pdfs", paths, "Unir PDFs")

    ctx.on_command("imgs_to_pdf", on_imgs_to_pdf)
    ctx.on_command("pdf_to_jpeg", on_pdf_to_jpeg)
    ctx.on_command("extract_images", on_extract_images)
    ctx.on_command("merge_pdfs", on_merge_pdfs)

    def on_stop():
        ctx.log("INFO", "PDF Tools plugin stopping.")

    ctx.on_stop(on_stop)
    ctx.emit_ready()
