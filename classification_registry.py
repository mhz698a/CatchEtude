# classification_registry.py
import json
import logging
from pathlib import Path
import config

class ClassificationRegistry:
    _instance = None

    def __init__(self):
        self.decisions = []
        self.load_config()

    def get_config_path(self) -> Path:
        return Path(config.CLASSIFICATIONS_JSON_PATH)

    def load_config(self):
        path = self.get_config_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.decisions = data.get("decisions", [])
                    self.decisions.sort(key=lambda d: d.get("order", 0))
                    return
            except Exception:
                logging.exception("Failed to load classifications.json, using defaults")
        
        # Si no existe, carga los valores iniciales y los guarda en disco
        self.load_defaults()
        self.save_config()

    def load_defaults(self):
        self.decisions = [
            {"id": 1, "name": "Keep in downloads", "name_key": "type_1", "icon": "descargas.png", "enabled": True, "order": 1, "handler": "keep", "year_mode": "none", "folder_source": "none", "allow_create": False},
            {"id": 2, "name": "Personajes", "name_key": "type_2", "icon": "me-gusta.png", "enabled": True, "order": 2, "handler": "subfolder_year", "year_mode": "required", "base_path": "{BASE_INTERNAL}/{year}/{year_prefix}. album", "folder_source": "filesystem", "allow_create": True},
            {"id": 3, "name": "Episodios", "name_key": "type_3", "icon": "película.png", "enabled": True, "order": 3, "handler": "episode", "year_mode": "required", "folder_source": "filesystem", "allow_create": True},
            {"id": 4, "name": "Musica", "name_key": "type_4", "icon": "música.png", "enabled": True, "order": 4, "handler": "subfolder_year", "year_mode": "required", "base_path": "{BASE_INTERNAL}/{year}/{year_prefix}. musica", "folder_source": "filesystem", "allow_create": True},
            {"id": 5, "name": "Academico", "name_key": "type_5", "icon": "aula-de-google.png", "enabled": True, "order": 5, "handler": "docs", "year_mode": "none", "folder_source": "onedrive", "allow_create": False},
            {"id": 6, "name": "Tramites", "name_key": "type_6", "icon": "identificación-verificada.png", "enabled": True, "order": 6, "handler": "docs", "year_mode": "none", "folder_source": "onedrive", "allow_create": False},
            {"id": 7, "name_key": "type_7", "icon": "Documentacion", "name_key": "type_7", "icon": "adobe-acrobat.png", "enabled": True, "order": 7, "handler": "linear_docs", "year_mode": "required", "folder_source": "filesystem", "allow_create": False},
            {"id": 8, "name_key": "type_8", "icon": "Overworld", "name_key": "mundo.png", "enabled": True, "order": 8, "handler": "overworld", "year_mode": "required", "base_path": "{BASE_INTERNAL}/{year}/{year_prefix}. overworld", "folder_source": "filesystem", "allow_create": True},
        ]

    def save_config(self):
        path = self.get_config_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"schema_version": 1, "decisions": self.decisions}, f, indent=4, ensure_ascii=False)
        except Exception:
            logging.exception("Failed to save classifications.json")

    def get_active_decisions(self):
        return [d for d in self.decisions if d.get("enabled", True)]

    def get_decision(self, type_id: int):
        for d in self.decisions:
            if d["id"] == type_id:
                return d
        return None

    def get_decision_name(self, decision: dict, lang: str = "es") -> str:
        name_val = decision.get("name")
        if isinstance(name_val, dict):
            return name_val.get(lang, name_val.get("es", ""))
        if name_val:
            return name_val
        # Fallback a clave de localización o ID
        return decision.get("name_key", f"type_{decision.get('id')}")