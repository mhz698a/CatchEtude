import unittest
import sys
from pathlib import Path

# Dynamic mocking of PyQt6 for headless/CI environments where PyQt6 is not installed
try:
    from PyQt6 import QtCore, QtWidgets, QtGui
    from PyQt6.QtWidgets import QApplication, QWidget, QListWidget, QListWidgetItem, QLabel, QProgressBar
    from PyQt6.QtCore import Qt
    HAS_PYQT = True
except ImportError:
    HAS_PYQT = False

    # Mock modules
    class MockQt:
        class ItemDataRole:
            UserRole = 0
        class AlignmentFlag:
            AlignLeft = 1
            AlignVCenter = 2
        class AspectRatioMode:
            KeepAspectRatio = 1
        class TransformationMode:
            SmoothTransformation = 1
        class WindowType:
            WindowStaysOnTopHint = 1

    class MockQtCore:
        Qt = MockQt
        class QObject:
            def __init__(self, parent=None): pass
        class QSize:
            def __init__(self, w, h): pass
        class QRect:
            def __init__(self, x, y, w, h): pass
        def pyqtSignal(*args, **kwargs):
            class MockSignal:
                def connect(self, slot): pass
                def emit(self, *args): pass
            return MockSignal()

    class MockQWidget:
        def __init__(self, parent=None):
            self.parent = parent
            self._layout = None
            self._style_sheet = ""
            self._height = 0
            self._width = 0
            self._max_height = 0
        def setStyleSheet(self, s):
            self._style_sheet = s
        def setFixedHeight(self, h):
            self._height = h
        def setMaximumHeight(self, h):
            self._max_height = h

    class MockQLabel(MockQWidget):
        def __init__(self, text="", parent=None):
            super().__init__(parent)
            self._text = text
            self._word_wrap = False
        def text(self):
            return self._text
        def setText(self, t):
            self._text = t
        def setWordWrap(self, b):
            self._word_wrap = b

    class MockQProgressBar(MockQWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._min = 0
            self._max = 100
            self._val = 0
        def setRange(self, min_val, max_val):
            self._min = min_val
            self._max = max_val
        def setValue(self, val):
            self._val = val
        def value(self):
            return self._val

    class MockQVBoxLayout:
        def __init__(self, parent=None):
            self.parent = parent
            self.widgets = []
            self.spacing = 0
            self.margins = (0, 0, 0, 0)
        def setContentsMargins(self, l, t, r, b):
            self.margins = (l, t, r, b)
        def setSpacing(self, s):
            self.spacing = s
        def addWidget(self, w):
            self.widgets.append(w)

    class MockQListWidgetItem:
        def __init__(self, parent=None):
            self.parent = parent
            self._size_hint = None
        def setSizeHint(self, sz):
            self._size_hint = sz

    class MockQListWidget(MockQWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.items = []
            self.item_widgets = {}
            self._scroll_mode = None
        def setVerticalScrollMode(self, mode):
            self._scroll_mode = mode
        def addItem(self, item):
            self.items.append(item)
        def setItemWidget(self, item, widget):
            self.item_widgets[item] = widget
        def row(self, item):
            try:
                return self.items.index(item)
            except ValueError:
                return -1
        def takeItem(self, row):
            if 0 <= row < len(self.items):
                item = self.items.pop(row)
                self.item_widgets.pop(item, None)
                return item
            return None
        def count(self):
            return len(self.items)

    class MockQtWidgets:
        QWidget = MockQWidget
        QLabel = MockQLabel
        QProgressBar = MockQProgressBar
        QVBoxLayout = MockQVBoxLayout
        QListWidget = MockQListWidget
        QListWidgetItem = MockQListWidgetItem
        class QAbstractItemView:
            class ScrollMode:
                ScrollPerPixel = 1

    sys.modules['PyQt6'] = type('MockPyQt6', (), {
        'QtCore': MockQtCore,
        'QtWidgets': MockQtWidgets,
        'QtGui': type('MockQtGui', (), {}),
    })
    sys.modules['PyQt6.QtCore'] = MockQtCore
    sys.modules['PyQt6.QtWidgets'] = MockQtWidgets
    sys.modules['PyQt6.QtGui'] = type('MockQtGui', (), {})

    # Enable our imports to succeed
    QtCore = MockQtCore
    QtWidgets = MockQtWidgets
    QWidget = MockQWidget
    QListWidget = MockQListWidget
    QListWidgetItem = MockQListWidgetItem
    QLabel = MockQLabel
    QProgressBar = MockQProgressBar
    Qt = MockQt

# Import the actual classes we want to test
from queue_movings_widget import MovingItemWidget, QueueMovingsWidget
from localization import LocalizationManager
from history_mgr import HistoryManager
import config

class TestQueueMovings(unittest.TestCase):
    def test_moving_item_widget(self):
        """Test that MovingItemWidget initializes properly and sets progress correctly."""
        widget = MovingItemWidget("test_file.mp4")
        self.assertEqual(widget.lbl_name.text(), "test_file.mp4")
        self.assertEqual(widget.progress_bar.value(), 0)

        # Test progress update inside widget
        widget.progress_bar.setValue(50)
        self.assertEqual(widget.progress_bar.value(), 50)

    def test_queue_movings_widget_ops(self):
        """Test add, progress update, and remove operations on QueueMovingsWidget."""
        list_widget = QueueMovingsWidget()

        src = Path("C:/Downloads/source.mp4")
        dst = Path("D:/Target/source.mp4")

        # Add movement
        list_widget.add_movement(src, dst)
        self.assertIn(src, list_widget._items_map)

        item, item_widget = list_widget._items_map[src]
        self.assertEqual(item_widget.lbl_name.text(), "source.mp4")
        self.assertEqual(item_widget.progress_bar.value(), 0)

        # Update progress
        list_widget.update_progress(src, 75)
        self.assertEqual(item_widget.progress_bar.value(), 75)

        # Remove movement
        list_widget.remove_movement(src)
        self.assertNotIn(src, list_widget._items_map)
        self.assertEqual(list_widget.count(), 0)

    def test_localization_keys(self):
        """Test that localization manager returns the correct translation for queue movings."""
        loc = LocalizationManager()
        # Save current language
        orig_lang = loc.current_lang()

        # Force Spanish
        loc.lang = "es"
        self.assertEqual(loc.get("lbl_queue_movings"), "Movimientos pendientes")

        # Force English
        loc.lang = "en"
        self.assertEqual(loc.get("lbl_queue_movings"), "Pending movements")

        # Restore language
        loc.lang = orig_lang

    def test_history_manager_get_last_move(self):
        """Test that HistoryManager retrieves the last move successfully."""
        mgr = HistoryManager(max_entries=5)
        # Clear/mock history for isolation
        mgr.history = []

        self.assertIsNone(mgr.get_last_move())

        src = Path("C:/Downloads/test.txt")
        dst = Path("D:/Target/test.txt")
        meta = {"atime": 0.0, "mtime": 0.0, "ctime": 0.0}

        mgr.record_move(src, dst, meta)

        last = mgr.get_last_move()
        self.assertIsNotNone(last)
        self.assertEqual(last["src"], str(src.absolute()))
        self.assertEqual(last["dst"], str(dst.absolute()))

        # Pop last
        popped = mgr.pop_last()
        self.assertEqual(popped, last)
        self.assertIsNone(mgr.get_last_move())

if __name__ == "__main__":
    unittest.main()
