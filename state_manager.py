import os, sys, time, shutil, logging, threading, queue
from enum import Enum, auto
from typing import Optional
from pathlib import Path
from utils import is_file_locked, is_temporary, sha256_file, resolve_duplicate, sanitize_windows_filename, flatten_downloads_root, setctime_blocking
from fallback_utils import safe_move_to_conflicts
from history_mgr import HistoryManager

from config import CONFLICTS, DOWNLOADS
from fallback_utils import compute_destination
from app_signals_mgr import AppSignals


# -----------------------
# State model
# -----------------------
class State(Enum):
    IDLE = auto()
    FILE_DETECTED = auto()
    USER_DECIDING = auto()
    APPLY_DECISION = auto()
    RESUME_WATCHER = auto()

# -----------------------
# StateManager - authoritative control over state and queue
# -----------------------
class StateManager:
    def __init__(self):
        self._state = State.IDLE
        self._history = HistoryManager()
        self._q = queue.Queue()
        self._active_file: Optional[Path] = None
        self._lock = threading.Lock()
        # notifier for UI (Qt signal) will be set externally by AppController
        self.notifier: Optional['AppSignals'] = None
        # thread to process queue
        self._thread = threading.Thread(target=self._process_queue, daemon=True)
        self._thread.start()
        # new 1
        self._last_requeue_log = None
        # new 2
        self._state_event = threading.Event()
        self._state_event.set()  # inicialmente libre
        # new 3
        self._enqueue_allowed = threading.Event()
        self._enqueue_allowed.set()

        self._pending: set[Path] = set()
        self._queue_list: list[Path] = []
        self._is_scanning = False


    def current_state(self) -> State:
        with self._lock:
            return self._state

    def has_pending_work(self) -> bool:
        """Returns True if there are files in the queue or being processed."""
        with self._lock:
            # We check _q and _active_file. _pending might contain files being moved in background.
            return not self._q.empty() or self._active_file is not None

    def _set_state(self, s: State):
        with self._lock:
            logging.info(f"State transition: {self._state} -> {s}")
            self._state = s
            self._state_event.set()

        # 🔽 NUEVO: cuando el sistema queda libre, aplanar descargas
        if s == State.IDLE:
            try:
                flatten_downloads_root()
                if not self._is_scanning:
                    threading.Thread(target=self._run_maintenance_scan, daemon=True).start()
            except Exception:
                logging.exception("Flatten downloads failed")

    def can_enqueue(self) -> bool:
        """Watcher reads this: only allow enqueue when NOT in USER_DECIDING."""
        return self.current_state() != State.USER_DECIDING

    def _emit_queue_update(self):
        if self.notifier:
            # Send copy of current queue list and active file path
            active_str = str(self._active_file) if self._active_file else ""
            self.notifier.queue_updated.emit(list(self._queue_list), active_str)

    def enqueue_file(self, p: Path):
        # ✅ deduplicación
        with self._lock:
            if p in self._pending:
                logging.debug(f"Already pending: {p}")
                return

            logging.info(f"Enqueueing file: {p}")
            self._pending.add(p)
            self._queue_list.append(p)
            self._q.put(p)
            self._emit_queue_update()

    def _process_queue(self):
        while True:
            try:
                # Wait until system is IDLE
                while self.current_state() != State.IDLE:
                    self._state_event.wait(2)
                    self._state_event.clear()

                p: Path = self._q.get()

                # Double check IDLE state after popping
                if self.current_state() != State.IDLE:
                    self._q.put(p)
                    continue

                # Prepare for detection
                with self._lock:
                    self._active_file = p
                    self._emit_queue_update()

                self._set_state(State.FILE_DETECTED)

                # Notify UI
                if self.notifier:
                    logging.info(f"Signaling UI for file: {p}")
                    self.notifier.file_detected.emit(str(p))
                else:
                    logging.error("No notifier connected; safe move to conflictos")
                    safe_move_to_conflicts(p)
                    self._active_file = None
                    self._set_state(State.IDLE)

                # Wait until the UI transitions state beyond FILE_DETECTED
                while self.current_state() == State.FILE_DETECTED:
                    self._state_event.wait(1)
                    self._state_event.clear()

            except Exception:
                logging.exception("StateManager queue processing error")
                time.sleep(1)

    def declare_user_deciding(self):
        """Call when UI has been shown and the system must freeze."""
        if self.current_state() not in (State.FILE_DETECTED,):
            logging.error("Invalid transition to USER_DECIDING")
            return False
        self._enqueue_allowed.clear()
        self._set_state(State.USER_DECIDING)
        return True

    def handover_active_file(self):
        """
        Transitions from USER_DECIDING to IDLE immediately,
        allowing the next file in queue to be processed while background
        tasks might still be running.
        """
        if self.current_state() != State.USER_DECIDING:
            logging.warning(f"handover_active_file called in state {self.current_state()}")
            return

        logging.info("Handing over active file; returning to IDLE")
        with self._lock:
            if self._active_file in self._queue_list:
                self._queue_list.remove(self._active_file)
            self._active_file = None
            self._emit_queue_update()

        self._set_state(State.IDLE)
        self._enqueue_allowed.set()

    def discard_active_file(self):
        """
        Used when a file is deleted or explicitly removed without a move task.
        Discards it from pending and returns to IDLE.
        """
        if self._active_file:
            src = self._active_file
            with self._lock:
                self._pending.discard(src)
                if src in self._queue_list:
                    self._queue_list.remove(src)
            logging.info(f"Discarded active file: {src.name}")

        self.handover_active_file()

        if not self._pending and self.notifier:
            self.notifier.queue_empty.emit()

    def undo_last_move(self) -> bool:
        """
        Undoes the last move operation.
        """
        entry = self._history.pop_last()
        if not entry:
            return False

        src = Path(entry["src"])
        dst = Path(entry["dst"])
        meta = entry["meta"]

        if not dst.exists():
            logging.error(f"Cannot undo: destination file missing: {dst}")
            return False

        try:
            # Re-resolve duplicate if someone else took the name in Downloads (unlikely)
            target = resolve_duplicate(src)
            shutil.move(str(dst), str(target))

            # Restore timestamps
            os.utime(target, (meta["atime"], meta["mtime"]))
            setctime_blocking(str(target), meta["ctime"])

            logging.info(f"Undo successful: {dst} -> {target}")

            # HOT-SWAP logic for Undo:
            if self.current_state() == State.USER_DECIDING and self._active_file:
                # Put current active file back to queue
                current = self._active_file
                logging.info(f"Undo Hot-Swap: putting {current.name} back to queue, showing {target.name}")
                with self._lock:
                    self._q.put(current)
                    if current in self._queue_list:
                        self._queue_list.remove(current)
                    self._queue_list.insert(0, target)
                    self._queue_list.insert(1, current)

                    # Show restored file immediately
                    self._active_file = target
                    self._pending.add(target)
                    self._emit_queue_update()

                self._set_state(State.FILE_DETECTED)
                if self.notifier:
                    self.notifier.file_detected.emit(str(target))
                return True

            # Normal re-enqueue
            self.enqueue_file(target)
            return True
        except Exception:
            logging.exception(f"Undo failed for {dst}")
            return False

    def apply_decision(self, decision: dict):
        """
        Aplica la decisión del usuario sobre el archivo activo.

        decision: dict con claves:
            action: 'move' o 'keep'
            movement_type: int (1..7)
            year: int o None
            sub: str o None
            new_name: str (sin extensión)
        """
        if self.current_state() != State.USER_DECIDING:
            logging.error("apply_decision llamado fuera de USER_DECIDING")
            return False

        self._set_state(State.APPLY_DECISION)
        p: Path = self._active_file

        if p is None or not p.exists():
            logging.error("Archivo activo faltante en apply_decision")
            self._set_state(State.RESUME_WATCHER)
            self._set_state(State.IDLE)
            return False

        try:
            # Obtener timestamp de creación según plataforma
            stat = p.stat()
            if sys.platform == "win32":
                ctime = stat.st_ctime
            elif hasattr(stat, "st_birthtime"):
                ctime = stat.st_birthtime
            else:
                ctime = stat.st_ctime # Linux: no hay creación confiable, usar st_ctime (cambio metadatos)

            if decision['action'] == 'keep':
                # mover a conflictos
                dest = resolve_duplicate(CONFLICTS / p.name)
                shutil.copy2(p, dest)  # preserva atime y mtime
                setctime_blocking(str(dest), ctime)  # preservar ctime/birthtime

                if sha256_file(p) == sha256_file(dest):
                    p.unlink(missing_ok=True)
                    logging.info(f"Archivo 'keep' movido a conflictos: {dest}")
                    self._history.record_move(p, dest, {"atime": stat.st_atime, "mtime": stat.st_mtime, "ctime": ctime})
                else:
                    logging.error("Integridad fallida al mover a conflictos; archivo original intacto")
                    dest.unlink(missing_ok=True)

            elif decision['action'] == 'move':
                # calcular destino final
                dest = compute_destination(decision, p)
                dest = resolve_duplicate(dest)
                shutil.copy2(p, dest)
                setctime_blocking(str(dest), ctime)

                if sha256_file(p) == sha256_file(dest):
                    p.unlink(missing_ok=True)
                    logging.info(f"Archivo movido a: {dest}")
                else:
                    logging.error("Integridad fallida al mover; enviando a conflictos")
                    dest.unlink(missing_ok=True)
                    conflict = resolve_duplicate(CONFLICTS / p.name)
                    shutil.copy2(p, conflict)
                    setctime_blocking(str(conflict), ctime)

            elif decision['action'] == 'move_custom':
                dest_dir = Path(decision['custom_dir'])
                dest_dir.mkdir(parents=True, exist_ok=True)

                newname = sanitize_windows_filename(decision.get('new_name', p.stem))
                dest = resolve_duplicate(dest_dir / (newname + p.suffix))

                shutil.copy2(p, dest)
                setctime_blocking(str(dest), ctime)

                if sha256_file(p) == sha256_file(dest):
                    p.unlink(missing_ok=True)
                    logging.info(f"Archivo movido (custom) a: {dest}")
                else:
                    logging.error("Integridad fallida en move_custom")
                    dest.unlink(missing_ok=True)
                    raise RuntimeError("Integrity check failed")

            else:
                logging.error(f"Acción desconocida en decisión: {decision['action']}")

        except Exception:
            logging.exception("Error durante apply_decision; intentando mover a conflictos")
            try:
                conflict = resolve_duplicate(CONFLICTS / p.name)
                shutil.copy2(p, conflict)
                setctime_blocking(str(conflict), ctime)
            except Exception:
                logging.exception("Fallo al mover archivo a conflictos como fallback")

        # ✅ quitar de pendientes
        if p:
            self._pending.discard(p)

        # finalizar
        self._active_file = None
        self._set_state(State.RESUME_WATCHER)
        self._set_state(State.IDLE)
        self._enqueue_allowed.set()
        return True

    def finalize_copied_file(self, decision: dict, copied_path: Path, src_meta: dict):
        if self.current_state() != State.USER_DECIDING:
            logging.error("finalize_copied_file fuera de USER_DECIDING")
            return False

        self._set_state(State.APPLY_DECISION)
        src = self._active_file

        try:
            # restaurar timestamps primero
            os.utime(
                copied_path,
                (src_meta["atime"], src_meta["mtime"])
            )
            setctime_blocking(str(copied_path), src_meta["ctime"])

            # validar integridad
            if sha256_file(src) != sha256_file(copied_path):
                logging.error("Hash mismatch")

            # borrar origen si aún existe
            if src and src.exists():
                src.unlink(missing_ok=True)

            logging.info(f"Archivo movido definitivamente a {copied_path}")

        except Exception:
            logging.exception("Fallo en finalize_copied_file")
            if src and src.exists():
                safe_move_to_conflicts(src)

        self._pending.discard(src)
        self._active_file = None
        self._set_state(State.RESUME_WATCHER)
        self._set_state(State.IDLE)
        return True

    def finalize_background_move(self, src: Path, dst: Path, src_meta: dict):
        """
        Completes the move process in the background.
        Used by the UI when it 'hot-swaps' to the next file.
        """
        try:
            with self._lock:
                if src in self._queue_list:
                    self._queue_list.remove(src)
                self._emit_queue_update()

            from utils import is_same_drive, update_folder_mtime
            # Restore timestamps
            os.utime(dst, (src_meta["atime"], src_meta["mtime"]))
            setctime_blocking(str(dst), src_meta["ctime"])

            # Update parent folder mtime to trigger character service update if applicable
            update_folder_mtime(dst.parent)

            # Handle cross-drive integrity if src still exists
            if src.exists():
                if not is_same_drive(src, dst):
                    if sha256_file(src) == sha256_file(dst):
                        src.unlink(missing_ok=True)
                        logging.info(f"Background move finalized (cross-drive): {dst}")
                        self._history.record_move(src, dst, src_meta)
                    else:
                        logging.error(f"Integrity check failed for {src}")
                        safe_move_to_conflicts(src)
                else:
                    # Same drive, src still exists? Fallback move might have been a copy
                    src.unlink(missing_ok=True)
                    logging.info(f"Background move finalized (same-drive fallback): {dst}")
                    self._history.record_move(src, dst, src_meta)
            else:
                logging.info(f"Background move finalized (native move): {dst}")
                self._history.record_move(src, dst, src_meta)

        except Exception:
            logging.exception("Error in finalize_background_move")
        finally:
            self._pending.discard(src)
            if not self._pending and self.notifier:
                self.notifier.queue_empty.emit()

    def maintenance_tick(self):
        """
        Tareas de mantenimiento que SOLO deben correr cuando el sistema está IDLE.
        """
        if self.current_state() != State.IDLE:
            return

        try:
            flatten_downloads_root()
            if not self._is_scanning:
                threading.Thread(target=self._run_maintenance_scan, daemon=True).start()
        except Exception:
            logging.exception("Maintenance tick failed")

    def _run_maintenance_scan(self):
        with self._lock:
            if self._is_scanning: return
            self._is_scanning = True

        try:
            scan_existing_downloads(self)
        finally:
            with self._lock:
                self._is_scanning = False


def scan_existing_downloads(state_manager: StateManager):
    try:
        now = time.time()
        for p in sorted(DOWNLOADS.iterdir()):
            if not p.is_file() or is_temporary(p):
                continue

            try:
                stat = p.stat()
                # If modified within the last 1 second, skip it (will be caught later)
                if now - stat.st_mtime < 1:
                    continue

                if is_file_locked(p):
                    continue

                state_manager.enqueue_file(p)
            except Exception:
                continue
    except Exception:
        logging.exception("Error during scan_existing_downloads")
