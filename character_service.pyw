"""
Character Service - Parallel service for character list data.
Servicio de Personajes: servicio paralelo para los datos de la lista de personajes.
"""

import sys
import os
import json
import time
import threading
import queue
import traceback
import win32event
import win32api
import ctypes
from pathlib import Path
from datetime import datetime
from dateutil.relativedelta import relativedelta
from PyQt6 import QtCore, QtNetwork
from config import BASE_INTERNAL, IMAGES_FOLDER, CRASH_REPORT_PATH, APP_NAME, MYAPPID
from character_cache_mgr import CharacterCacheManager

SERVICE_MUTEX_NAME = "CatchEtudeCharacterServiceMutex"
SERVER_NAME = "CatchEtudeCharacterServer"
WATCHDOG_SERVER_NAME = "CatchEtudeLogServer"
ERROR_ALREADY_EXISTS = 183

# Custom logging level for character list activities (copied from log_mgr)
CHARS_LEVEL_NAME = "CHARS"

class CharacterService(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.active_generation = 0
        self.active_year = None
        self.pause_event = threading.Event()
        self.pause_event.set() # Set means NOT paused (allowed to run)
        self.task_queue = queue.Queue()
        self.worker_thread = threading.Thread(target=self._queue_worker, daemon=True)
        self.worker_thread.start()
        
        self.server = QtNetwork.QLocalServer(self)
        self.server.newConnection.connect(self._on_new_connection)
        QtNetwork.QLocalServer.removeServer(SERVER_NAME)
        if not self.server.listen(SERVER_NAME):
            self._log_error(f"Character Server could not start: {self.server.errorString()}")
        
        self.monitor_thread = threading.Thread(target=self._monitor_process, daemon=True)
        self.monitor_thread.start()

        self._closing = False
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._cleanup)

    def _log_to_watchdog(self, level, message):
        socket = QtNetwork.QLocalSocket()
        socket.connectToServer(WATCHDOG_SERVER_NAME)
        if socket.waitForConnected(100):
            data = json.dumps({"cmd": "log", "level": level, "message": message})
            socket.write(data.encode('utf-8'))
            socket.waitForBytesWritten(100)
            socket.disconnectFromServer()

    def _log_info(self, msg): self._log_to_watchdog("INFO", msg)
    def _log_char(self, msg): self._log_to_watchdog("CHARS", msg)
    def _log_error(self, msg): self._log_to_watchdog("ERROR", msg)

    def _on_new_connection(self):
        socket = self.server.nextPendingConnection()
        socket.readyRead.connect(lambda: self._read_socket(socket))

    def _read_socket(self, socket):
        data = socket.readAll().data().decode('utf-8')
        try:
            msg = json.loads(data)
            cmd = msg.get("cmd")
            if cmd == "load":
                year = msg.get("year")
                gen = msg.get("generation")
                self._handle_load_request(year, gen, socket)
            elif cmd == "pause":
                self.pause_event.clear()
                self._log_info("Character Service: Scanning paused")
            elif cmd == "resume":
                self.pause_event.set()
                self._log_info("Character Service: Scanning resumed")
            elif cmd == "quit":
                self._cleanup()
                QtCore.QCoreApplication.quit()
            elif cmd == "update_pid":
                # Deprecated
                pass
        except Exception as e:
            self._log_error(f"Character Service error reading socket: {e}")

    def _handle_load_request(self, year, gen, request_socket):
        self.active_generation = gen
        self.active_year = year
        self.task_queue.put((year, gen))

    def _queue_worker(self):
        while True:
            year, gen = self.task_queue.get()
            try:
                self._loader_worker(year, gen)
            except Exception:
                self._log_error(f"Error in Character Service queue worker: {traceback.format_exc()}")
            finally:
                self.task_queue.task_done()

    def _send_update(self, msg_dict):
        """Sends an update back to the main app via a new connection."""
        # Main app's CharacterListModel will listen on a specific name or we can reuse a name.
        # Better: Main app listens on "CatchEtudeCharacterClient"
        socket = QtNetwork.QLocalSocket()
        socket.connectToServer("CatchEtudeCharacterClient")
        if socket.waitForConnected(500):
            socket.write(json.dumps(msg_dict).encode('utf-8'))
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()

    def _loader_worker(self, year, generation):
        base = BASE_INTERNAL / str(year)
        prefix = f"{year - 2003:02d}"
        
        try:
            if not (base.exists() and base.is_dir()):
                return

            # Force HDD spin-up
            try:
                next(os.scandir(str(base)), None)
            except Exception: pass
            
            root_path = None
            try:
                with os.scandir(str(base)) as it:
                    for entry in it:
                        if not entry.is_dir(): continue
                        name_low = entry.name.lower()
                        if (prefix in name_low and IMAGES_FOLDER in name_low) or (IMAGES_FOLDER in name_low):
                            root_path = entry.path
                            break
            except Exception: pass

            if not root_path: return

            cache_mgr = CharacterCacheManager(year)
            active_paths = set()
            items_data = []
            needs_validation = []

            with os.scandir(root_path) as it:
                entries = sorted([e for e in it if e.is_dir()], key=lambda e: e.name)

            for entry in entries:
                abs_p = entry.path
                active_paths.add(abs_p)
                
                cached = cache_mgr.get_folder_data(abs_p)
                if cached:
                    item = {
                        "year": year, "num": cached["metadata"]["num"], "alter": cached["metadata"]["alter"],
                        "name": cached["metadata"]["name"], "birthday_iso": cached["metadata"]["birthday_iso"],
                        "origin_age": cached["metadata"]["origin_age"], "file_count": cached["file_count"],
                        "total_size": cached["total_size"], "path": abs_p,
                        "age_str": cached["age_str"], "size_mb_str": cached["size_mb_str"]
                    }
                else:
                    meta = self._parse_name_metadata(entry.name)
                    age_str, _ = self._format_ui_strings(meta["birthday_iso"], 0)
                    item = {
                        "year": year, "num": meta["num"], "alter": meta["alter"],
                        "name": meta["name"], "birthday_iso": meta["birthday_iso"],
                        "origin_age": meta["origin_age"], "file_count": 0, "total_size": 0, "path": abs_p,
                        "age_str": age_str, "size_mb_str": "..."
                    }
                
                items_data.append(item)
                needs_validation.append((len(items_data)-1, abs_p, entry.name))

            # PASS 0: Send Batch
            if generation == self.active_generation:
                self._send_update({"cmd": "batch", "generation": generation, "items": items_data})

            # PASS 1 & 2: Validation
            for idx, abs_p, entry_name in needs_validation:
                
                # 🔴 Si cambió generación, abortar
                if generation != self.active_generation:
                    return
                
                self.pause_event.wait()
                
                try:
                    st = os.stat(abs_p)
                    mtime_ns = st.st_mtime_ns
                except Exception: continue

                cached = cache_mgr.get_folder_data(abs_p)
                do_full_scan = True
                # Trusting mtime and checking existence in cache
                if cached and cached.get("mtime_ns") == mtime_ns:
                    do_full_scan = False
                
                if do_full_scan:
                    self._log_char(f"Deep scanning: {entry_name}")
                    count, size = self._scan_folder_scandir(abs_p, generation)
                    
                    if count is None:
                        return  # cancelado

                    # Note: count/size will not be None because we removed early return from scan_folder_scandir below

                    try:
                        current_entry_count = sum(1 for _ in os.scandir(abs_p))
                    except Exception: current_entry_count = 0

                    meta = self._parse_name_metadata(entry_name)
                    age_str, size_mb_str = self._format_ui_strings(meta["birthday_iso"], size)
                    
                    item = items_data[idx]
                    item["file_count"] = count
                    item["total_size"] = size
                    item["age_str"] = age_str
                    item["size_mb_str"] = size_mb_str
                    
                    cache_mgr.update_folder(abs_p, mtime_ns, current_entry_count, count, size, meta, age_str, size_mb_str)
                    if generation == self.active_generation:
                        self._send_update({"cmd": "update", "generation": generation, "index": idx, "item": item})
                else:
                    if generation == self.active_generation:
                        if items_data[idx]["size_mb_str"] == "...":
                            self._send_update({"cmd": "update", "generation": generation, "index": idx, "item": items_data[idx]})
                
                if idx % 10 == 0: time.sleep(0.01)

            # Always save cache after processing all items for this year
            cache_mgr.remove_stale_entries(active_paths)
            cache_mgr.save()
            if generation == self.active_generation:
                self._log_char(f"Character loading complete for year {year}")

        except Exception as e:
            self._log_error(f"Error in Character Service loader: {traceback.format_exc()}")

    def _parse_name_metadata(self, folder_name: str) -> dict:
        num = 0; alter = folder_name; name = "_"; birthday_iso = "1970-01-01"; origin_age = 0
        if '.' in folder_name:
            try:
                meta = folder_name.split('.', 1)[1]
                parts = [p.strip() for p in meta.split(';')]
                if len(parts) >= 1 and parts[0] != "_" and parts[0].isdigit(): num = int(parts[0])
                if len(parts) >= 2 and parts[1] != "_": alter = parts[1]
                if len(parts) >= 3 and parts[2] != "_": name = parts[2]
                if len(parts) >= 4 and parts[3] not in ("_", None, ""):
                    try: datetime.fromisoformat(parts[3]); birthday_iso = parts[3]
                    except ValueError: pass
                if len(parts) >= 5 and parts[4] != "_" and parts[4].isdigit(): origin_age = int(parts[4])
            except Exception: pass
        return {"num": num, "alter": alter, "name": name, "birthday_iso": birthday_iso, "origin_age": origin_age}

    def _format_ui_strings(self, birthday_iso: str, total_size: int) -> tuple[str, str]:
        try: birthday = datetime.fromisoformat(birthday_iso)
        except Exception: birthday = datetime(1970, 1, 1)
        if birthday.year == 1970: age_str = ""
        else:
            delta = relativedelta(datetime.now(), birthday)
            age_str = f"{delta.years}a {delta.months}m {delta.days}d"
        size_mb_str = f"{total_size / (1024*1024):.1f} MB"
        return age_str, size_mb_str

    def _scan_folder_scandir(self, path_str: str, generation: int):
        total_size = 0; total_count = 0; BATCH_CHECK = 50
        try:
            with os.scandir(path_str) as it:
                for i, entry in enumerate(it):
                    
                    # 🔴 Cada BATCH_CHECK archivos chequeamos cancelación
                    if i % BATCH_CHECK == 0:
                        # Si cambió generación → abortar inmediatamente
                        if generation != self.active_generation:
                            return None, None

                        # Pausa cooperativa
                        self.pause_event.wait()
                        
                    try:
                        if entry.is_file(follow_symlinks=False):
                            st = entry.stat(follow_symlinks=False)
                            total_size += st.st_size
                            total_count += 1
                            
                    except (PermissionError, FileNotFoundError, OSError): continue
        except Exception: pass
        return total_count, total_size

    def _monitor_process(self):
        while True:
            try:
                handle = win32event.OpenMutex(win32event.SYNCHRONIZE, False, APP_NAME)
                if handle:
                    win32event.WaitForSingleObject(handle, win32event.INFINITE)
                    win32api.CloseHandle(handle)
                    break
                else:
                    time.sleep(1)
            except Exception:
                break
        
        self._cleanup()
        QtCore.QCoreApplication.quit()

    def _cleanup(self):
        if self._closing:
            return
        self._closing = True
        try:
            if self.server.isListening():
                self.server.close()
        except Exception:
            pass
        try:
            QtNetwork.QLocalServer.removeServer(SERVER_NAME)
        except Exception:
            pass

def crash_handler(etype, value, tb):
    err_msg = "".join(traceback.format_exception(etype, value, tb))
    # Try to log to watchdog if possible
    try:
        socket = QtNetwork.QLocalSocket()
        socket.connectToServer(WATCHDOG_SERVER_NAME)
        if socket.waitForConnected(200):
            data = json.dumps({"cmd": "log", "level": "ERROR", "message": f"CHARACTER SERVICE CRASHED:\n{err_msg}"})
            socket.write(data.encode('utf-8'))
            socket.waitForBytesWritten(200)
            socket.disconnectFromServer()
    except Exception: pass
    
    try: CRASH_REPORT_PATH.write_text(f"CHAR_SERVICE_CRASH:\n{err_msg}", encoding='utf-8')
    except Exception: pass
    sys.exit(1)

def main():
    sys.excepthook = crash_handler
    
    # Set AppUserModelID for Taskbar
    try: ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(MYAPPID)
    except Exception: pass

    # Mutex for single instance
    mutex = win32event.CreateMutex(None, False, SERVICE_MUTEX_NAME)
    if win32api.GetLastError() == ERROR_ALREADY_EXISTS:
        return
    
    # Detect if main service is running
    try:
        handle = win32event.OpenMutex(win32event.SYNCHRONIZE, False, APP_NAME)
        if not handle:
            print("Main app not running, character service exiting.")
            return
        win32api.CloseHandle(handle)
    except Exception:
        print("Main app not running, character service exiting.")
        return

    app = QtCore.QCoreApplication(sys.argv)
    
    service = CharacterService()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
