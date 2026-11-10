# decision_dispatcher.py
import logging
from pathlib import Path
import config
from classification_mgr import get_base_path_for_type_year, get_base_path_for_docs

class DecisionDispatcher:
    def __init__(self, panel):
        self.panel = panel

    def dispatch_subfolder_click(self, decision: dict, name: str):
        handler = decision.get("handler")
        
        if handler == "keep":
            self.panel.keep_action_clicked.emit(name)
        elif handler == "linear_docs":
            self.panel.linear_docs_action_clicked.emit(name)
        else:
            self.panel._remember_recent_subfolder(name)
            self.panel.subfolder_clicked.emit(name)

    def resolve_base_path(self, decision: dict, year: int | None) -> Path | None:
        handler = decision.get("handler")
        type_id = decision["id"]
        
        # 1. Resolver mediante plantilla base_path si está definida en el JSON
        base_path_template = decision.get("base_path")
        if base_path_template:
            base_str = base_path_template
            base_str = base_str.replace("{BASE_INTERNAL}", str(config.BASE_INTERNAL))
            if year is not None:
                base_str = base_str.replace("{year}", str(year))
                prefix = f"{year - 2003:02d}"
                base_str = base_str.replace("{year_prefix}", prefix)
            return Path(base_str)

        # 2. Respaldos por defecto según el handler
        if handler in ("subfolder_year", "episode", "overworld", "move_to_subfolder"):
            if year is not None:
                return get_base_path_for_type_year(type_id, year)
        elif handler == "docs":
            return get_base_path_for_docs(type_id)
            
        return None

    def requires_year(self, decision: dict) -> bool:
        year_mode = decision.get("year_mode")
        if year_mode == "required":
            return True
        if year_mode == "none":
            return False
        
        # Fallback basado en el handler si year_mode no está presente
        handler = decision.get("handler")
        return handler in ("subfolder_year", "episode", "overworld", "linear_docs", "move_to_subfolder")