# /// catch-etude-plugin
# [plugin]
# id = "catchetude.fast-image-viewer"
# name = "Fast Image Viewer"
# version = "1.0.0"
# api_version = 1
# capabilities = ["ui_action"]
# events = []
#
# [[action_buttons]]
# id = "btn_fast_image_viewer"
# label = "View"
# command = "view_image"
# file_extensions = [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg"]
# /// end catch-etude-plugin

"""
Fast Image Viewer Plugin for CatchEtude.
Displays an interactive image viewer window with scroll zoom, slider control, and saved window geometry.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ui_utils_mgr import load_stylesheet

from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class FastImageViewerWindow(QMainWindow):
    """Interactive Image Viewer Window with zoom slider and wheel controls."""

    def __init__(self, plugin_id: str):
        super().__init__()
        self.plugin_id = plugin_id
        self.config_file = self._get_config_path()

        self.zoom_level = 100  # percentage
        self.pixmap_item = None
        self._updating_slider = False

        self._build_ui()
        self._load_window_settings()

    def _get_config_path(self) -> Path:
        appdata = Path(os.getenv("APPDATA", Path.home()))
        config_dir = appdata / "CatchEtude" / "plugins-config"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / f"{self.plugin_id}.json"

    def _build_ui(self):
        self.setWindowTitle("Fast Image Viewer")
        self.setMinimumSize(400, 300)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Graphics Scene & View
        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.view.setRenderHints(
            QtGui.QPainter.RenderHint.Antialiasing
            | QtGui.QPainter.RenderHint.SmoothPixmapTransform
        )
        self.view.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.view.viewport().installEventFilter(self)

        main_layout.addWidget(self.view, 1)

        # Bottom Bar
        bottom_bar = QWidget(self)
        bottom_bar.setFixedHeight(36)
        bottom_bar.setStyleSheet(load_stylesheet("fast_image_viewer_bottom_bar.css"))

        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(10, 0, 10, 0)
        bottom_layout.setSpacing(10)

        self.lbl_info = QLabel("No image loaded", bottom_bar)
        bottom_layout.addWidget(self.lbl_info)

        bottom_layout.addStretch()

        self.lbl_zoom = QLabel("100%", bottom_bar)
        self.lbl_zoom.setFixedWidth(45)
        self.lbl_zoom.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        bottom_layout.addWidget(self.lbl_zoom)

        self.zoom_slider = QSlider(Qt.Orientation.Horizontal, bottom_bar)
        self.zoom_slider.setRange(10, 500)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setFixedWidth(150)
        self.zoom_slider.valueChanged.connect(self._on_slider_value_changed)
        bottom_layout.addWidget(self.zoom_slider)

        main_layout.addWidget(bottom_bar)

    def load_image(self, file_path: Path):
        self.scene.clear()
        self.pixmap_item = None

        if not file_path.exists():
            self.lbl_info.setText("File does not exist")
            return

        reader = QtGui.QImageReader(str(file_path))
        reader.setAutoTransform(True)
        img = reader.read()

        if img.isNull():
            self.lbl_info.setText(f"Failed to load image: {file_path.name}")
            return

        pixmap = QtGui.QPixmap.fromImage(img)
        self.pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.pixmap_item)
        self.scene.setSceneRect(0, 0, pixmap.width(), pixmap.height())

        self.setWindowTitle(f"Fast Image Viewer - {file_path.name}")
        self.lbl_info.setText(f"{file_path.name} ({pixmap.width()} x {pixmap.height()})")

        # Fit image in view initially if larger than view
        self.view.resetTransform()
        self._updating_slider = True
        self.zoom_level = 100
        self.zoom_slider.setValue(100)
        self.lbl_zoom.setText("100%")
        self._updating_slider = False

    def _on_slider_value_changed(self, value: int):
        if self._updating_slider:
            return

        self.zoom_level = value
        self.lbl_zoom.setText(f"{value}%")
        self._apply_zoom()

    def _apply_zoom(self):
        scale = self.zoom_level / 100.0
        self.view.resetTransform()
        self.view.scale(scale, scale)

    def eventFilter(self, source, event):
        if source == self.view.viewport() and event.type() == QtCore.QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            if delta != 0:
                factor = 1.1 if delta > 0 else 0.9
                new_zoom = int(self.zoom_level * factor)
                new_zoom = max(10, min(500, new_zoom))
                if new_zoom != self.zoom_level:
                    self.zoom_level = new_zoom
                    self._updating_slider = True
                    self.zoom_slider.setValue(new_zoom)
                    self.lbl_zoom.setText(f"{new_zoom}%")
                    self._updating_slider = False
                    self._apply_zoom()
            return True
        return super().eventFilter(source, event)

    def _load_window_settings(self):
        try:
            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                w = data.get("width", 800)
                h = data.get("height", 600)
                is_max = data.get("is_maximized", False)
                self.resize(w, h)
                if is_max:
                    self.showMaximized()
        except Exception:
            pass

    def _save_window_settings(self):
        try:
            data = {}
            if self.config_file.exists():
                with open(self.config_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            if not self.isMaximized():
                data["width"] = self.width()
                data["height"] = self.height()
            data["is_maximized"] = self.isMaximized()

            tmp_file = self.config_file.with_suffix(".tmp")
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            tmp_file.replace(self.config_file)
        except Exception:
            pass

    def keyPressEvent(self, event: QtGui.QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self._save_window_settings()
        super().closeEvent(event)

    def resizeEvent(self, event):
        if not self.isMaximized():
            self._save_window_settings()
        super().resizeEvent(event)


viewer_window = None


def run_plugin(ctx):
    ctx.log("INFO", "Fast Image Viewer plugin initialized.")

    def on_view_image(args):
        global viewer_window
        paths = (args or {}).get("paths", [])
        if not paths:
            ctx.log("WARNING", "No paths provided for view_image command.")
            return

        file_path = Path(paths[0])
        ctx.log("INFO", f"Opening Fast Image Viewer for {file_path}")

        if viewer_window is None or not viewer_window.isVisible():
            viewer_window = FastImageViewerWindow(ctx.plugin_id)

        viewer_window.load_image(file_path)
        viewer_window.show()
        viewer_window.raise_()
        viewer_window.activateWindow()

    ctx.on_command("view_image", on_view_image)

    def on_stop():
        global viewer_window
        if viewer_window is not None:
            viewer_window.close()
            viewer_window = None
        ctx.log("INFO", "Fast Image Viewer plugin stopping.")

    ctx.on_stop(on_stop)
    ctx.emit_ready()
