import unittest
import sys
from pathlib import Path

# Mock ctypes windll and WinDLL for Linux/CI environment
import ctypes
if not hasattr(ctypes, 'windll'):
    class MockWinDLL:
        def __getattr__(self, name):
            class MockDLL:
                def __getattr__(self, func):
                    return lambda *args, **kwargs: 1
            return MockDLL()
    ctypes.windll = MockWinDLL()
    ctypes.WinDLL = lambda name: MockWinDLL()

# Dynamic mocking of Windows-specific and PyQt6 modules for headless Linux/CI environments
try:
    import win32file
except ImportError:
    # Mock pywin32 modules
    sys.modules['win32file'] = type('MockWin32File', (), {})
    sys.modules['win32con'] = type('MockWin32Con', (), {})
    sys.modules['pywintypes'] = type('MockPyWinTypes', (), {
        'error': Exception
    })

try:
    import send2trash
except ImportError:
    # Mock send2trash
    sys.modules['send2trash'] = type('MockSend2Trash', (), {
        'send2trash': lambda x: True
    })

try:
    from PyQt6 import QtCore, QtWidgets, QtGui, QtNetwork
    from PyQt6.QtWidgets import QApplication, QWidget, QListWidget, QListWidgetItem, QLabel, QProgressBar
    from PyQt6.QtCore import Qt
    HAS_PYQT = True
except ImportError:
    HAS_PYQT = False

    # Mock modules
    class MockQt:
        class ItemDataRole:
            UserRole = 0
            UserRolePlusOne = 1
        class AlignmentFlag:
            AlignLeft = 1
            AlignVCenter = 2
        class AspectRatioMode:
            KeepAspectRatio = 1
        class TransformationMode:
            SmoothTransformation = 1
        class WindowType:
            WindowStaysOnTopHint = 1
    MockQt.ItemDataRole.UserRole = 0

    class MockQThread:
        def __init__(self, parent=None):
            self.started = MockSignal()
        def start(self): pass
        def quit(self): pass
        def wait(self): pass
        def deleteLater(self): pass

    class MockSignal:
        def connect(self, slot): pass
        def emit(self, *args, **kwargs): pass

    class MockQtCore:
        Qt = MockQt
        QThread = MockQThread
        class QObject:
            def __init__(self, parent=None): pass
        class QSize:
            def __init__(self, w, h): pass
        class QRect:
            def __init__(self, x, y, w, h): pass
        def pyqtSignal(*args, **kwargs):
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

    class MockQLocalSocket:
        def __init__(self, parent=None): pass
        def connectToServer(self, name): pass
        def waitForConnected(self, ms): return False
        def write(self, data): pass
        def waitForBytesWritten(self, ms): pass
        def disconnectFromServer(self): pass

    sys.modules['PyQt6'] = type('MockPyQt6', (), {
        'QtCore': MockQtCore,
        'QtWidgets': MockQtWidgets,
        'QtGui': type('MockQtGui', (), {}),
        'QtNetwork': type('MockQtNetwork', (), {
            'QLocalSocket': MockQLocalSocket
        }),
    })
    sys.modules['PyQt6.QtCore'] = MockQtCore
    sys.modules['PyQt6.QtWidgets'] = MockQtWidgets
    sys.modules['PyQt6.QtGui'] = type('MockQtGui', (), {})
    sys.modules['PyQt6.QtNetwork'] = type('MockQtNetwork', (), {
        'QLocalSocket': MockQLocalSocket
    })

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
from background_move_mgr import BackgroundMoveManager
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

    def test_background_move_mgr_prioritization(self):
        """Test enqueuing and prioritization in BackgroundMoveManager."""
        # Create a mock StateManager for initialisation
        class MockStateManager:
            def __init__(self):
                self._lock = ctypes.windll.kernel32

        mgr = BackgroundMoveManager(MockStateManager())

        # Create temp files of different sizes
        p_light = Path("light_file.txt")
        p_heavy = Path("heavy_file.txt")
        p_medium = Path("medium_file.txt")

        # Mock size returns or write dummy data
        p_light.write_bytes(b"A" * 10)         # 10 bytes
        p_medium.write_bytes(b"A" * 100)       # 100 bytes
        p_heavy.write_bytes(b"A" * 1000)       # 1000 bytes

        try:
            # Mock the active workers dictionary so they don't actually run,
            # letting everything stay in pending_tasks to test sorting.
            mgr._max_concurrent = 0

            mgr.enqueue_move(p_light, Path("target_light.txt"), {}, {})
            mgr.enqueue_move(p_heavy, Path("target_heavy.txt"), {}, {})
            mgr.enqueue_move(p_medium, Path("target_medium.txt"), {}, {})

            # Since _max_concurrent is 0, they should all be in _pending_tasks sorted by size (heaviest first)
            self.assertEqual(len(mgr._pending_tasks), 3)

            # Heaviest first (1000 bytes)
            self.assertEqual(mgr._pending_tasks[0]["src"], p_heavy)
            # Medium next (100 bytes)
            self.assertEqual(mgr._pending_tasks[1]["src"], p_medium)
            # Lightest last (10 bytes)
            self.assertEqual(mgr._pending_tasks[2]["src"], p_light)

        finally:
            # Clean up temp files
            for p in (p_light, p_medium, p_heavy):
                if p.exists():
                    p.unlink()

if __name__ == "__main__":
    unittest.main()
