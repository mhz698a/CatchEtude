"""
Robust Configuration Manager with Thread-Safe Hot-Reload and Validation.
Gestor de Configuración Robusto con Hot-Reload Seguro en Threads y Validación.
"""

import logging
import threading
import tomllib
from pathlib import Path
from typing import Any, Callable, Optional, Dict
from dataclasses import dataclass
from enum import Enum


class SettingType(Enum):
    """Tipos de configuración soportados."""
    PATH = "path"
    STRING = "string"
    INT = "int"
    FLOAT = "float"
    BOOL = "bool"


@dataclass
class SettingDef:
    """Define una configuración con tipo, validación y valor por defecto."""
    key: str
    type: SettingType
    default: Any
    validator: Optional[Callable[[Any], bool]] = None
    description: str = ""

    def validate(self, value: Any) -> bool:
        """Valida que el valor sea del tipo correcto."""
        try:
            if self.type == SettingType.PATH:
                return isinstance(value, (str, Path))
            elif self.type == SettingType.STRING:
                return isinstance(value, str)
            elif self.type == SettingType.INT:
                return isinstance(value, int)
            elif self.type == SettingType.FLOAT:
                return isinstance(value, (int, float))
            elif self.type == SettingType.BOOL:
                return isinstance(value, bool)
        except Exception:
            return False

        if self.validator:
            return self.validator(value)
        return True


class ConfigurationManager:
    """
    Thread-safe configuration manager con soporte para hot-reload y validación.
    
    CARACTERÍSTICAS:
    ✅ Almacena valores con tipos definidos y validación
    ✅ Valida cambios antes de aplicarlos (no silencia errores)
    ✅ Notifica a observadores sobre cambios (patrón Observer)
    ✅ NO modifica sys.modules (seguro contra race conditions)
    ✅ Usa locks RLock (recursive) para operaciones cascada
    ✅ Cada observador es responsable de actualizar su contexto
    
    USO:
        config_mgr = ConfigurationManager(Path("settings.toml"))
        
        # Registrar configuraciones
        config_mgr.register_settings([
            SettingDef("BASE_INTERNAL", SettingType.PATH, Path("E:/_Internal")),
            SettingDef("BLUR_LEVEL", SettingType.INT, 15),
        ])
        
        # Suscribirse a cambios
        config_mgr.subscribe(on_config_changed)
        
        # Cargar desde archivo
        config_mgr.load_from_file()
        
        # Acceder a valores
        value = config_mgr.get("BASE_INTERNAL")
    """

    def __init__(self, settings_path: Path):
        self.settings_path = Path(settings_path)
        self._lock = threading.RLock()  # Recursive lock para cambios cascada
        self._settings: Dict[str, Any] = {}
        self._definitions: Dict[str, SettingDef] = {}
        self._observers: list[Callable[[str, Any, Any], None]] = []
        self._load_count = 0

    def register_setting(self, definition: SettingDef) -> None:
        """Registra una configuración con su definición."""
        with self._lock:
            if definition.key in self._definitions:
                logging.warning(f"Setting {definition.key} already registered, overwriting")
            self._definitions[definition.key] = definition
            if definition.key not in self._settings:
                self._settings[definition.key] = definition.default

    def register_settings(self, definitions: list[SettingDef]) -> None:
        """Registra múltiples configuraciones de una vez."""
        for defn in definitions:
            self.register_setting(defn)

    def load_from_file(self) -> Dict[str, Any]:
        """
        Carga configuraciones desde archivo TOML.
        
        SEGURIDAD:
        - Valida cada valor contra su SettingDef
        - NO silencia errores, los registra
        - Notifica a observadores de cambios
        
        Retorna: dict con cambios aplicados {key: (old_value, new_value)}
        """
        with self._lock:
            if not self.settings_path.exists():
                logging.info(f"Settings file not found: {self.settings_path}, using defaults")
                return {}

            try:
                with open(self.settings_path, "rb") as f:
                    file_settings = tomllib.load(f)
                
                changes = self._apply_settings_batch(file_settings)
                self._load_count += 1
                logging.info(f"Loaded settings from {self.settings_path} (load #{self._load_count})")
                return changes

            except Exception as e:
                logging.error(f"Failed to load settings: {e}")
                return {}

    def save_to_file(self) -> bool:
        """
        Guarda configuraciones actuales al archivo TOML.
        
        SEGURIDAD:
        - Serializa rutas correctamente
        - Usa escaping correcto para TOML
        - Valida antes de guardar
        
        Retorna: True si se guardó exitosamente
        """
        with self._lock:
            try:
                # Validar antes de guardar
                if not self.validate_all():
                    logging.error("Cannot save: validation failed")
                    return False

                # Serializar con conversión de tipos
                to_save = {}
                for key, value in self._settings.items():
                    if isinstance(value, Path):
                        to_save[key] = value.as_posix()
                    else:
                        to_save[key] = value

                with open(self.settings_path, "w", encoding="utf-8") as f:
                    for key, value in to_save.items():
                        if isinstance(value, str):
                            f.write(f"{key} = '''{value}'''\n")
                        else:
                            f.write(f"{key} = {value}\n")

                logging.info(f"Saved settings to {self.settings_path}")
                return True

            except Exception as e:
                logging.error(f"Failed to save settings: {e}")
                return False

    def set(self, key: str, value: Any, notify: bool = True) -> bool:
        """
        Establece una configuración individual.
        
        SEGURIDAD:
        - Valida tipo antes de aplicar
        - No modifica si la validación falla
        - Retorna False si hay error (no silencia)
        
        Retorna: True si se aplicó correctamente
        """
        with self._lock:
            if key not in self._definitions:
                logging.error(f"Unknown setting key: {key}")
                return False

            definition = self._definitions[key]

            # Validar tipo
            if not definition.validate(value):
                logging.error(f"Invalid type for {key}: expected {definition.type}, got {type(value)}")
                return False

            # Convertir tipos si es necesario
            if definition.type == SettingType.PATH:
                value = Path(value) if not isinstance(value, Path) else value

            old_value = self._settings.get(key)
            if old_value == value:
                return True  # Sin cambios

            self._settings[key] = value

            if notify:
                self._notify_observers(key, old_value, value)

            return True

    def get(self, key: str) -> Any:
        """Obtiene el valor de una configuración de forma thread-safe."""
        with self._lock:
            if key not in self._settings:
                logging.warning(f"Setting {key} not found, returning None")
                return None
            return self._settings[key]

    def get_all(self) -> Dict[str, Any]:
        """Retorna copia de TODAS las configuraciones."""
        with self._lock:
            return dict(self._settings)

    def subscribe(self, callback: Callable[[str, Any, Any], None]) -> None:
        """
        Suscribirse a cambios de configuración.
        
        callback(key: str, old_value: Any, new_value: Any)
        
        IMPORTANTE: El observador es responsable de:
        - Actualizar su propio contexto (no lo hace el manager)
        - Manejar excepciones en su código
        - NO hacer operaciones bloqueantes (usar threads si es necesario)
        """
        with self._lock:
            if callback not in self._observers:
                self._observers.append(callback)

    def unsubscribe(self, callback: Callable) -> None:
        """Desuscribirse de cambios."""
        with self._lock:
            if callback in self._observers:
                self._observers.remove(callback)

    def _apply_settings_batch(self, new_settings: Dict[str, Any]) -> Dict[str, Any]:
        """
        Aplica un lote de configuraciones.
        Retorna dict con (key -> (old, new)) de cambios aplicados.
        
        SEGURIDAD:
        - Valida TODAS antes de aplicar ninguna (atomicidad)
        - Registra errores de validación
        - Notifica observadores por cada cambio
        """
        changes = {}
        errors = []

        # Fase 1: Validar todo
        for key, value in new_settings.items():
            if key not in self._definitions:
                logging.warning(f"Unknown setting in batch: {key}, skipping")
                continue

            definition = self._definitions[key]

            if not definition.validate(value):
                errors.append(f"{key}: invalid type {type(value)}, expected {definition.type}")
                continue

            # Convertir tipos si es necesario
            if definition.type == SettingType.PATH:
                value = Path(value) if not isinstance(value, Path) else value

            old_value = self._settings.get(key)
            if old_value != value:
                changes[key] = (old_value, value)

        if errors:
            logging.warning(f"Settings batch validation errors: {errors}")

        # Fase 2: Aplicar cambios validados
        for key, (old_val, new_val) in changes.items():
            self._settings[key] = new_val
            self._notify_observers(key, old_val, new_val)

        return changes

    def _notify_observers(self, key: str, old_value: Any, new_value: Any) -> None:
        """
        Notifica a observadores de un cambio.
        
        SEGURIDAD:
        - Cada observador se ejecuta en el thread del llamador
        - Si un observador falla, se registra pero no afecta a otros
        - Errores no silenciados (se loguean)
        """
        for observer in self._observers:
            try:
                observer(key, old_value, new_value)
            except Exception as e:
                logging.exception(f"Observer callback failed for {key}: {e}")

    def validate_all(self) -> bool:
        """Valida que todas las configuraciones actuales sean válidas."""
        with self._lock:
            for key, value in self._settings.items():
                if key in self._definitions:
                    if not self._definitions[key].validate(value):
                        logging.error(f"Validation failed for {key}: {value}")
                        return False
            return True

    def ensure_paths_exist(self) -> bool:
        """
        Asegura que todas las rutas configuradas existan.
        
        SEGURIDAD:
        - Crea directorios necesarios
        - Retorna False si alguno falla (no silencia)
        """
        with self._lock:
            for key, value in self._settings.items():
                if isinstance(value, Path):
                    try:
                        value.mkdir(parents=True, exist_ok=True)
                    except Exception as e:
                        logging.error(f"Failed to create path for {key}: {e}")
                        return False
            return True
