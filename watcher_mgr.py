"""
Watcher module - Monitors the Downloads folder for new files.
Módulo Watcher: monitorea la carpeta de Descargas en busca de nuevos archivos.
"""

import logging
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent
from PyQt6 import QtCore

import config
from utils import is_temporary, is_file_locked, folder_is_safe_to_flatten, run_in_threadpool
from log_mgr import safe_thread_logger


class WatcherHandler(FileSystemEventHandler):
    """
    Event handler for watchdog that filters and processes file system events.
    Manejador de eventos para watchdog que filtra y procesa eventos del sistema de archivos.
    """
    def __init__(self, enqueue_callback):
        super().__init__()
        self.enqueue = enqueue_callback
        self._monitoring = set()
        self._lock = QtCore.QMutex() # PyQt thread-safe mutex or standard threading.Lock is fine, QMutex is great. Let's use QMutex.

    def on_created(self, event):
        """Called when a file or directory is created."""
        self._handle(Path(event.src_path))

    def on_moved(self, event):
        """Called when a file or directory is moved."""
        self._handle(Path(event.dest_path))

    def _handle(self, p: Path):
        """
        Validates the file and enqueues it if it meets the criteria.
        Schedules monitoring task on the global thread pool to wait for stability.
        """
        try:
            # Check if it's in the monitored folder (case-insensitive and resolve path comparison)
            try:
                if not (p.parent == config.DOWNLOADS or p.parent.resolve() == config.DOWNLOADS.resolve()):
                    return
            except Exception:
                if p.parent != config.DOWNLOADS:
                    return

            # Filter temporary files
            if is_temporary(p):
                logging.debug(f"[Watcher] Ignored temporary file: {p.name}")
                return

            # Lock monitoring set
            locker = QtCore.QMutexLocker(self._lock)
            if p in self._monitoring:
                return
            self._monitoring.add(p)
            # Release lock
            del locker

            # Schedule stability monitor task in global thread pool
            run_in_threadpool(self._monitor_file, p)

        except Exception:
            logging.exception("[Watcher] Error in WatcherHandler._handle")

    @safe_thread_logger("WatcherMonitor")
    def _monitor_file(self, p: Path):
        """Monitors a file or directory until stable and ready for enqueuing."""
        try:
            logging.info(f"[Watcher] Detected candidate path: {p.name}. Monitoring stability...")

            while True:
                if not p.exists():
                    logging.info(f"[Watcher] Path disappeared during monitoring: {p.name}")
                    break

                try:
                    if p.is_dir():
                        time.sleep(1)
                        if not p.exists(): break
                        if folder_is_safe_to_flatten(p):
                            logging.info(f"[Watcher] Directory is stable and safe: '{p.name}'")
                            self.enqueue(p)
                            break
                        continue

                    stat1 = p.stat()
                    size1 = stat1.st_size
                    mtime1 = stat1.st_mtime

                    time.sleep(1) # Wait 1 second

                    if not p.exists(): break
                    stat2 = p.stat()
                    size2 = stat2.st_size
                    mtime2 = stat2.st_mtime

                    if size1 == size2 and mtime1 == mtime2:
                        # File is stable, now check if locked
                        if not is_file_locked(p):
                            logging.info(f"[Watcher] File is stable and unlocked: '{p.name}' (Size: {size1} bytes)")
                            self.enqueue(p)
                            break
                        else:
                            logging.info(f"[Watcher] File is stable but currently locked by another process, retrying: {p.name}")
                    else:
                        logging.info(f"[Watcher] File is still writing: {p.name} (size: {size1}->{size2}, mtime: {mtime1}->{mtime2})")
                except (FileNotFoundError, PermissionError) as e:
                    logging.warning(f"[Watcher] Access error during monitoring (vanishing?): {p.name} - {e}")
                    break
        except Exception:
            logging.exception(f"[Watcher] Error monitoring path: {p}")
        finally:
            locker = QtCore.QMutexLocker(self._lock)
            self._monitoring.discard(p)


class WatcherThread(QtCore.QThread):
    """
    Background QThread that runs the watchdog observer.
    Hilo en segundo plano que ejecuta el observador de watchdog.
    """
    def __init__(self, enqueue_callback, parent=None):
        super().__init__(parent)
        self.enqueue_callback = enqueue_callback
        self.observer = Observer()

    @safe_thread_logger("WatcherObserver")
    def run(self):
        """Starts the observer and waits."""
        try:
            handler = WatcherHandler(self.enqueue_callback)
            self.observer.schedule(handler, str(config.DOWNLOADS), recursive=False)
            self.observer.start()
            logging.info(f"[Watcher] Observer thread successfully started on: {config.DOWNLOADS}")

            # Keep the thread alive
            while self.observer.is_alive():
                self.msleep(1000)
        except Exception:
            logging.exception("[Watcher] Error in WatcherThread.run")
        finally:
            self.stop()

    def stop(self):
        """Stops the observer safely."""
        try:
            self.observer.stop()
            self.observer.join()
            logging.info("[Watcher] Observer thread stopped safely")
        except Exception as e:
            print("[Watcher] Error to stop the observer")
