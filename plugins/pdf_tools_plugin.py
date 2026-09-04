# /// catch-etude-plugin
# [plugin]
# id = "catchetude.pdf-tools"
# name = "Herramientas PDF Plugin"
# version = "1.0.0"
# api_version = 1
# capabilities = ["background_task", "tray_action"]
# events = []
#
# [[tray_actions]]
# id = "imgs_to_pdf"
# label = "IMGs a PDF"
# command = "imgs_to_pdf"
#
# [[tray_actions]]
# id = "pdf_to_jpeg"
# label = "PDF a JPEG"
# command = "pdf_to_jpeg"
#
# [[tray_actions]]
# id = "extract_images"
# label = "Extraer imágenes de PDF"
# command = "extract_images"
#
# [[tray_actions]]
# id = "merge_pdfs"
# label = "Unir PDFs"
# command = "merge_pdfs"
# /// end catch-etude-plugin

"""
PDF Tools Plugin for CatchEtude.
Provides conversion and image extraction utilities for PDF files.
"""

import sys
from pathlib import Path
from PyQt6.QtWidgets import QFileDialog

import config
from pdf_gui_runner import run_pdf_task


def run_plugin(ctx):
    ctx.log("INFO", "PDF Tools plugin initialized.")

    def on_imgs_to_pdf(args):
        file_filter = "Imágenes (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff)"
        files, _ = QFileDialog.getOpenFileNames(None, "Seleccionar imágenes", str(config.DOWNLOADS), file_filter)
        if files:
            paths = [Path(f) for f in files]
            run_pdf_task(None, "imgs_to_pdf", paths, "IMGs a PDF")

    def on_pdf_to_jpeg(args):
        file_filter = "Archivos PDF (*.pdf)"
        files, _ = QFileDialog.getOpenFileNames(None, "Seleccionar PDFs", str(config.DOWNLOADS), file_filter)
        if files:
            paths = [Path(f) for f in files]
            run_pdf_task(None, "pdf_to_jpeg", paths, "PDF a JPEG")

    def on_extract_images(args):
        file_filter = "Archivos PDF (*.pdf)"
        files, _ = QFileDialog.getOpenFileNames(None, "Seleccionar PDFs", str(config.DOWNLOADS), file_filter)
        if files:
            paths = [Path(f) for f in files]
            run_pdf_task(None, "extract_images", paths, "Extraer imágenes de PDF")

    def on_merge_pdfs(args):
        file_filter = "Archivos PDF (*.pdf)"
        files, _ = QFileDialog.getOpenFileNames(None, "Seleccionar PDFs", str(config.DOWNLOADS), file_filter)
        if files:
            paths = [Path(f) for f in files]
            run_pdf_task(None, "merge_pdfs", paths, "Unir PDFs")

    ctx.on_command("imgs_to_pdf", on_imgs_to_pdf)
    ctx.on_command("pdf_to_jpeg", on_pdf_to_jpeg)
    ctx.on_command("extract_images", on_extract_images)
    ctx.on_command("merge_pdfs", on_merge_pdfs)

    def on_stop():
        ctx.log("INFO", "PDF Tools plugin stopping.")

    ctx.on_stop(on_stop)
    ctx.emit_ready()
