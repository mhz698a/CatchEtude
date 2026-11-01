# /// catch-etude-plugin
# [plugin]
# id = "catchetude.pdf-tools"
# name = "Herramientas PDF Plugin"
# version = "1.1.0"
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
# [[tray_actions]]
# id = "images_to_ico"
# label = "Imagen a ICO"
# command = "images_to_ico"
# group = "Convertir Archivo"
#
# [[tray_actions]]
# id = "images_to_png"
# label = "Imagen a PNG"
# command = "images_to_png"
# group = "Convertir Archivo"
#
# [[tray_actions]]
# id = "images_to_jpg"
# label = "Imagen a JPG"
# command = "images_to_jpg"
# group = "Convertir Archivo"
#
# [[tray_actions]]
# id = "svg_to_png"
# label = "SVG a PNG"
# command = "svg_to_png"
# group = "Convertir Archivo"
#
# [[tray_actions]]
# id = "svg_to_ico"
# label = "SVG a ICO"
# command = "svg_to_ico"
# group = "Convertir Archivo"
#
# [[tray_actions]]
# id = "audio_to_mp3"
# label = "Audio a MP3"
# command = "audio_to_mp3"
# group = "Convertir Archivo"
#
# [[tray_actions]]
# id = "word_to_pdf"
# label = "Word a PDF"
# command = "word_to_pdf"
# group = "Convertir Archivo"
#
# [[action_buttons]]
# id = "btn_convert_raster_images"
# label = "Convertir imagen"
# file_extensions = [".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif", ".ico", ".avif", ".heic", ".jp2", ".j2k", ".dds", ".pcx", ".tga", ".ppm", ".pbm", ".pgm", ".psd"]
# menu_items = [
#     { label = "Image a ICO", command = "images_to_ico" },
#     { label = "Image a PNG", command = "images_to_png" },
#     { label = "Image a JPG", command = "images_to_jpg" },
# ]
#
# [[action_buttons]]
# id = "btn_convert_svg"
# label = "Convertir SVG"
# file_extensions = [".svg"]
# menu_items = [
#     { label = "SVG a PNG", command = "svg_to_png" },
#     { label = "SVG a ICO", command = "svg_to_ico" },
# ]
#
# [[action_buttons]]
# id = "btn_convert_audio"
# label = "Convertir audio"
# file_extensions = [".mp3", ".wav", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wma", ".aiff", ".aif", ".ape", ".mpc", ".wv", ".tta", ".mka", ".3gp"]
# menu_items = [
#     { label = "Audio a MP3", command = "audio_to_mp3" },
# ]
#
# [[action_buttons]]
# id = "btn_word_to_pdf"
# label = "Word a PDF"
# file_extensions = [".doc", ".docx", ".docm", ".dot", ".dotx", ".dotm", ".rtf"]
# menu_items = [
#     { label = "Convertir a PDF", command = "word_to_pdf" },
# ]
#
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

    def on_conversion(task_type, title, file_filter, dialog_title):
        def handler(args):
            paths = selected_paths(args, file_filter, dialog_title)
            if paths:
                run_pdf_task(None, task_type, paths, title)
        return handler

    conversion_commands = {
        "images_to_ico": on_conversion(
            "images_to_ico", "Imágenes a ICO", "Todos los archivos (*)", "Seleccionar imágenes"
        ),
        "images_to_png": on_conversion(
            "images_to_png", "Imágenes a PNG", "Todos los archivos (*)", "Seleccionar imágenes"
        ),
        "images_to_jpg": on_conversion(
            "images_to_jpg", "Imágenes a JPG", "Todos los archivos (*)", "Seleccionar imágenes"
        ),
        "svg_to_png": on_conversion(
            "svg_to_png", "SVG a PNG", "Archivos SVG (*.svg)", "Seleccionar SVG"
        ),
        "svg_to_ico": on_conversion(
            "svg_to_ico", "SVG a ICO", "Archivos SVG (*.svg)", "Seleccionar SVG"
        ),
        "audio_to_mp3": on_conversion(
            "audio_to_mp3", "Audio a MP3", "Todos los archivos (*)", "Seleccionar archivos de audio"
        ),
        "word_to_pdf": on_conversion(
            "word_to_pdf", "Word a PDF",
            "Documentos Word (*.doc *.docx *.docm *.dot *.dotx *.dotm *.rtf)",
            "Seleccionar documentos Word"
        ),
    }
    for command, handler in conversion_commands.items():
        ctx.on_command(command, handler)

    def on_stop():
        ctx.log("INFO", "PDF Tools plugin stopping.")

    ctx.on_stop(on_stop)
    ctx.emit_ready()
