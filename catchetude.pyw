"""
CatchEtude - Main application entry point.
CatchEtude - Punto de entrada principal de la aplicación.

Initializes the application, services, and the main UI window.
Inicializa la aplicación, los servicios y la ventana principal de la interfaz.
"""

import sys
import logging
import threading
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

from config import (
    APP_NAME, LOG_PATH, ICON_PATH, CONFIG_PATH, DOWNLOADS
) 
from utils import flatten_downloads_root
from state_manager import StateManager, scan_existing_downloads
from watcher_mgr import WatcherThread
from app_signals_mgr import AppSignals
from log_mgr import setup_logging
from service_mgr import (
    ensure_single_instance, add_to_startup, crash_handler,
    start_watchdog, start_character_service, stop_parallel_services
)
from main_window_mgr import MainWindow
from PyQt6 import QtCore

def main():
    # Set exception hook for crash reporting
    sys.excepthook = crash_handler
    
    # Initialize Application
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(ICON_PATH))
    app.setQuitOnLastWindowClosed(False)
    
    # Ensure single instance
    mutex = ensure_single_instance()
    
    # Setup logging
    setup_logging(LOG_PATH)
    
    try:
        # Stop any lingering parallel services before starting new ones
        stop_parallel_services(timeout=10.0)

        # Start background services
        start_watchdog()
        start_character_service()
        
        # Initialize State and Signals
        state_manager = StateManager()
        signals = AppSignals()
        state_manager.notifier = signals
        
        # # Start Watcher
        # watcher = WatcherThread(state_manager.enqueue_file)
        # app.aboutToQuit.connect(watcher.stop)
        # watcher.start()
        
        watcher = WatcherThread(state_manager.enqueue_file)
        watcher.start()

        def _cleanup_services():
            try:
                stop_parallel_services(timeout=10.0)
            except Exception:
                logging.exception("Failed to stop parallel services during shutdown")
            try:
                watcher.stop()
            except Exception:
                logging.exception("Failed to stop watcher")

        app.aboutToQuit.connect(_cleanup_services)
        
        
        # Initial scan and flattening
        threading.Thread(
            target=lambda: (flatten_downloads_root(), scan_existing_downloads(state_manager)), 
            daemon=True
        ).start()

        # Create Main Window
        win = MainWindow(state_manager, signals)
        
        # Maintenance timers
        maintenance_timer = QtCore.QTimer()
        maintenance_timer.setInterval(3000)
        maintenance_timer.timeout.connect(state_manager.maintenance_tick)
        maintenance_timer.start()
        
        rescan_timer = QtCore.QTimer()
        rescan_timer.setInterval(30 * 60 * 1000)
        rescan_timer.timeout.connect(lambda: threading.Thread(
            target=scan_existing_downloads, args=(state_manager,), daemon=True).start())
        rescan_timer.start()
        
        # Startup registration
        mypath = str(Path(sys.argv[0]).resolve())
        try:
            add_to_startup(APP_NAME, mypath, True)
        except Exception:
            logging.exception("add_to_startup failed")

        sys.exit(app.exec())
    except Exception:
        logging.exception("Unhandled exception in main")
        crash_handler(*sys.exc_info())

if __name__ == "__main__":
    main()
