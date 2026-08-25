"""
CatchEtude - Main application entry point.
CatchEtude - Punto de entrada principal de la aplicación.

Initializes the application, services, and the main UI window.
Inicializa la aplicación, los servicios y la ventana principal de la interfaz.
"""

import sys
import faulthandler
import logging
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from utils import flatten_downloads_root, run_in_threadpool
from state_manager import StateManager, scan_existing_downloads
from watcher_mgr import WatcherThread
from app_signals_mgr import AppSignals
from log_mgr import setup_logging
from service_mgr import (
    ensure_single_instance, add_to_startup, crash_handler, start_watchdog,
    start_character_service, start_overworld_service, stop_parallel_services
)
import config
from main_window_mgr import MainWindow
from PyQt6 import QtCore
from PyQt6.QtCore import qInstallMessageHandler

DEBUGER = False
plugin_mgr = None

def qt_handler(mode, context, message):
    logging.error("QT: %s", message)

if DEBUGER:
    faulthandler.enable(all_threads=True)

    if hasattr(sys, "stderr"):
        faulthandler.dump_traceback_later(10, repeat=True)

    qInstallMessageHandler(qt_handler)

def main():
    # Set exception hook for crash reporting
    sys.excepthook = crash_handler

    # Initialize Application
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(config.ICON_PATH))
    app.setQuitOnLastWindowClosed(False)

    try:
        stop_parallel_services(timeout=10.0)
    except TimeoutError:
        logging.warning("Previous services cleanup timed out, proceeding anyway")
    except Exception as e:
        logging.warning(f"Previous services cleanup failed ({type(e).__name__}): {e}, proceeding with startup")

    # Ensure single instance
    mutex = ensure_single_instance()

    # Setup logging
    setup_logging(config.LOG_PATH)

    # Initialize Plugin Manager
    global plugin_mgr
    from plugin_manager import PluginManager
    plugin_mgr = PluginManager()
    plugin_mgr.start_enabled_plugins()

    try:
        # Start background services
        start_watchdog()
        start_character_service()
        start_overworld_service()

        # Initialize State and Signals
        state_manager = StateManager()
        signals = AppSignals()
        state_manager.notifier = signals

        # # Start Watcher
        watcher = WatcherThread(state_manager.enqueue_file)
        watcher.start()

        def _cleanup_services():
            try:
                plugin_mgr.shutdown()
            except Exception:
                logging.exception("Failed to shutdown plugin manager")
            try:
                stop_parallel_services(timeout=10.0)
            except Exception:
                logging.exception("Failed to stop parallel services during shutdown")
            try:
                watcher.stop()
            except Exception:
                logging.exception("Failed to stop watcher")

        app.aboutToQuit.connect(_cleanup_services)

        # Notify plugins that app started
        plugin_mgr.publish_event("app_started", {})

        # Connect signals for plugins
        def _on_file_detected(file_info):
            plugin_mgr.publish_event("file_detected", {
                "name": file_info.name,
                "path": str(file_info),
            })

        def _on_move_finished(data):
            plugin_mgr.publish_event("move_finished", {
                "src": str(data.get("src", "")),
                "dst": str(data.get("dst", "")),
                "category": data.get("category", ""),
            })

        signals.file_detected.connect(_on_file_detected)
        signals.move_finished.connect(_on_move_finished)

        # Initial scan and flattening
        run_in_threadpool(lambda: (flatten_downloads_root(), scan_existing_downloads(state_manager)))

        # Create Main Window
        win = MainWindow(state_manager, signals)

        # Start Thread Reporter for Main App
        from log_mgr import start_thread_reporter
        start_thread_reporter("Main App", win)

        # Maintenance timers
        maintenance_timer = QtCore.QTimer()
        maintenance_timer.setInterval(3000)
        maintenance_timer.timeout.connect(state_manager.maintenance_tick)
        maintenance_timer.start()

        rescan_timer = QtCore.QTimer()
        rescan_timer.setInterval(30 * 60 * 1000)
        rescan_timer.timeout.connect(lambda: run_in_threadpool(scan_existing_downloads, state_manager))
        rescan_timer.start()

        # Startup registration
        mypath = str(Path(sys.argv[0]).resolve())
        try:
            add_to_startup(config.APP_NAME, mypath, True)
        except Exception:
            logging.exception("add_to_startup failed")

        try:
            if config.CRASH_REPORT_PATH.exists():
                config.CRASH_REPORT_PATH.unlink()
        except FileNotFoundError:
            deleted = 1  # File already deleted, expected
        except PermissionError:
            logging.warning(f"Cannot delete crash report (permission denied): {config.CRASH_REPORT_PATH}")
        except Exception as e:
            logging.warning(f"Failed to delete crash report: {e}")

        sys.exit(app.exec())

    except Exception:
        logging.exception("Unhandled exception in main")
        crash_handler(*sys.exc_info())

if __name__ == "__main__":
    main()
