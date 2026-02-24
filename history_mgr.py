import json
import logging
import shutil
from pathlib import Path
from typing import Optional, Dict, List
from config import HISTORY_PATH

class HistoryManager:
    """
    Manages a persistent history of file move operations to allow Undo.
    Gestiona un historial persistente de operaciones de movimiento para permitir Deshacer.
    """
    def __init__(self, max_entries: int = 50):
        self.max_entries = max_entries
        self.history: List[Dict] = self._load_history()

    def _load_history(self) -> List[Dict]:
        if HISTORY_PATH.exists():
            try:
                with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                logging.exception("Failed to load history")
        return []

    def _save_history(self):
        try:
            with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, indent=4)
        except Exception:
            logging.exception("Failed to save history")

    def record_move(self, src: Path, dst: Path, meta: Dict):
        """Records a move operation."""
        entry = {
            "src": str(src.absolute()),
            "dst": str(dst.absolute()),
            "meta": meta,
            "timestamp": Path(dst).stat().st_mtime if dst.exists() else 0
        }
        self.history.append(entry)
        if len(self.history) > self.max_entries:
            self.history.pop(0)
        self._save_history()

    def pop_last(self) -> Optional[Dict]:
        if not self.history:
            return None
        entry = self.history.pop()
        self._save_history()
        return entry
