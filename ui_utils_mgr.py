"""
UI utility components for CatchEtude.
Componentes de utilidad de interfaz para CatchEtude.
"""

import os
from pathlib import Path
from PyQt6 import QtCore, QtWidgets, QtGui
from PyQt6.QtWidgets import QFileIconProvider
from PyQt6.QtCore import Qt

class QueueDelegate(QtWidgets.QStyledItemDelegate):
    """Delegate for rendering the download queue with thumbnails/icons."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._thumb_cache = {}

    def paint(self, painter, option, index):
        painter.save()
        
        path_str = index.data(Qt.ItemDataRole.UserRole)
        is_active = index.data(Qt.ItemDataRole.UserRole + 1)
        p = Path(path_str)
        
        rect = option.rect
        
        if is_active:
            # Highlight active file
            painter.fillRect(rect, QtGui.QColor("#e1f5fe"))
            painter.setPen(QtGui.QColor("#01579b"))
        elif option.state & QtWidgets.QStyle.StateFlag.State_Selected:
            painter.fillRect(rect, option.palette.highlight())
            painter.setPen(option.palette.highlightedText().color())
        else:
            painter.setPen(option.palette.text().color())
            
        # Draw icon/thumbnail
        icon_rect = QtCore.QRect(rect.left() + 5, rect.top() + 5, 40, 40)
        
        if path_str not in self._thumb_cache:
            if p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}:
                reader = QtGui.QImageReader(path_str)
                reader.setAutoTransform(True)
                img_size = reader.size()
                if img_size.isValid():
                    reader.setScaledSize(img_size.scaled(40, 40, Qt.AspectRatioMode.KeepAspectRatio))
                img = reader.read()
                if not img.isNull():
                    self._thumb_cache[path_str] = QtGui.QPixmap.fromImage(img)
                else:
                    self._thumb_cache[path_str] = QFileIconProvider().icon(QtCore.QFileInfo(path_str))
            else:
                self._thumb_cache[path_str] = QFileIconProvider().icon(QtCore.QFileInfo(path_str))
        
        obj = self._thumb_cache[path_str]
        if isinstance(obj, QtGui.QPixmap):
            # Center pixmap in icon_rect
            pix_rect = obj.rect()
            pix_rect.moveCenter(icon_rect.center())
            painter.drawPixmap(pix_rect.topLeft(), obj)
        else:
            obj.paint(painter, icon_rect)
        
        # Draw text
        text_rect = rect.adjusted(55, 0, -5, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, p.name)
        
        painter.restore()

    def sizeHint(self, option, index):
        return QtCore.QSize(200, 50)
