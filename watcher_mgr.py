"""
Watcher module - Monitors the Downloads folder for new files.
Módulo Watcher: monitorea la carpeta de Descargas en busca de nuevos archivos.
"""

import logging
import threading
import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileMovedEvent

import config
from utils import is_temporary, is_file_locked
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
        self._lock = threading.Lock()

    def on_created(self, event):
        """Called when a file or directory is created."""
        if not event.is_directory:
            self._handle(Path(event.src_path))

    def on_moved(self, event):
        """Called when a file or directory is moved."""
        if not event.is_directory:
            self._handle(Path(event.dest_path))

    def _handle(self, p: Path):
        """
        Validates the file and enqueues it if it meets the criteria.
        Spawns a background thread to monitor stability.
        """
        try:
            # Check if it's in the monitored folder
            if p.parent != config.DOWNLOADS:
                return

            # Filter temporary files
            if is_temporary(p):
                logging.debug(f"[Watcher] Ignored temporary file: {p.name}")
                return

            with self._lock:
                if p in self._monitoring:
                    return
                self._monitoring.add(p)

            # Spawn a thread to wait for stability
            threading.Thread(target=self._monitor_file, args=(p,), daemon=True).start()

        except Exception:
            logging.exception("[Watcher] Error in WatcherHandler._handle")

    @safe_thread_logger("WatcherMonitor")
    def _monitor_file(self, p: Path):
        """Monitors a file until its size and mtime are stable and it's no longer locked."""
        try:
            logging.info(f"[Watcher] Detected candidate file: {p.name}. Monitoring stability...")

            while True:
                if not p.exists():
                    logging.info(f"[Watcher] File disappeared during monitoring: {p.name}")
                    break

                try:
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
            logging.exception(f"[Watcher] Error monitoring file: {p}")
        finally:
            with self._lock:
                self._monitoring.discard(p)


class WatcherThread(threading.Thread):
    """
    Background thread that runs the watchdog observer.
    Hilo en segundo plano que ejecuta el observador de watchdog.
    """
    def __init__(self, enqueue_callback):
        super().__init__(daemon=True)
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
                self.observer.join(1)
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
