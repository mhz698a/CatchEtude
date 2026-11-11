"""Persistent, validated classification definitions for CatchEtude."""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import config

_UNSET_FINGERPRINT = object()

DEFAULT_DECISIONS: list[dict[str, Any]] = [
 {"id":1,"name_key":"type_1","icon":"descargas.png","enabled":True,"order":1,"handler":"keep","year_mode":"none","folder_source":"none","requires_internal":False,"allow_create":False,"allow_rename":False,"allow_delete":False},
 {"id":2,"name_key":"type_2","icon":"me-gusta.png","enabled":True,"order":2,"handler":"move_to_subfolder","year_mode":"required","base_path":"{BASE_INTERNAL}/{year}","folder_contains":"{IMAGES_FOLDER}","folder_fallback":"{BASE_INTERNAL}/{year}/{year_prefix}. {IMAGES_FOLDER}","folder_source":"filesystem","requires_internal":True,"allow_create":True,"allow_rename":True,"allow_delete":True,"behaviour_second_line":"character_metadata"},
 {"id":3,"name_key":"type_3","icon":"película.png","enabled":True,"order":3,"handler":"move_to_subfolder","year_mode":"required","base_path":"{BASE_INTERNAL}/{year}","folder_contains":"___[","folder_fallback":"{BASE_INTERNAL}/{year}","folder_source":"filesystem","requires_internal":True,"allow_create":True,"allow_rename":True,"allow_delete":True,"behaviour_second_line":"last_file"},
 {"id":4,"name_key":"type_4","icon":"música.png","enabled":True,"order":4,"handler":"move_to_subfolder","year_mode":"required","base_path":"{BASE_INTERNAL}/{year}","folder_contains":"{MUSIC_FOLDER}","folder_fallback":"{BASE_INTERNAL}/{year}/{year_prefix}. {MUSIC_FOLDER}","folder_source":"filesystem","requires_internal":True,"allow_create":True,"allow_rename":True,"allow_delete":True},
 {"id":5,"name_key":"type_5","icon":"aula-de-google.png","enabled":True,"order":5,"handler":"move_to_subfolder","year_mode":"none","base_path":"{ONEDRIVE_DOCS}","folder_source":"filesystem","requires_internal":False,"allow_create":True,"allow_rename":True,"allow_delete":True},
 {"id":6,"name_key":"type_6","icon":"identificación-verificada.png","enabled":True,"order":6,"handler":"move_to_subfolder","year_mode":"none","base_path":"{ONEDRIVE_DOCTOS_FAMILIA}","folder_source":"filesystem","requires_internal":False,"allow_create":True,"allow_rename":True,"allow_delete":True},
 {"id":7,"name_key":"type_7","icon":"adobe-acrobat.png","enabled":True,"order":7,"handler":"linear_docs","year_mode":"required","base_path":"{BASE_INTERNAL}/{year}/{year_prefix}. {ACROBAT_FOLDER}","folder_source":"none","requires_internal":True,"allow_create":False,"allow_rename":False,"allow_delete":False},
 {"id":8,"name_key":"type_8","icon":"mundo.png","enabled":True,"order":8,"handler":"move_to_subfolder","year_mode":"required","base_path":"{BASE_INTERNAL}/{year}","folder_contains":"{OVERWORLD_FOLDER}","folder_fallback":"{BASE_INTERNAL}/{year}/{year_prefix}. {OVERWORLD_FOLDER}","folder_source":"filesystem","requires_internal":True,"allow_create":True,"allow_rename":True,"allow_delete":True,"behaviour_second_line":"overworld_metadata"},
]
_LEGACY_HANDLERS={"subfolder_year":"move_to_subfolder","episode":"move_to_subfolder","docs":"move_to_subfolder","overworld":"move_to_subfolder"}
_OLD_DEFAULT_PATHS={2:"{BASE_INTERNAL}/{year}/{year_prefix}. album",4:"{BASE_INTERNAL}/{year}/{year_prefix}. musica",8:"{BASE_INTERNAL}/{year}/{year_prefix}. overworld"}
_LEGACY_NAMES={1:"Keep in downloads",2:"Personajes",3:"Episodios",4:"Musica",5:"Academico",6:"Tramites"}

class ClassificationRegistry:
    SCHEMA_VERSION=2
    def __init__(self, settings_path: Path | None=None):
        self.settings_path=Path(settings_path if settings_path is not None else config.CLASSIFICATIONS_JSON_PATH)
        self.decisions: list[dict[str,Any]]=[]
        self.last_save_error: str | None = None
        self.last_save_message: str | None = None
        self.load_error: str | None = None
        self.load_config()

    def get_config_path(self)->Path:
        return self.settings_path

    def get_config_fingerprint(self) -> str | None:
        """Return a content hash, or None when the configuration does not exist."""
        try:
            payload = self.get_config_path().read_bytes()
        except FileNotFoundError:
            return None
        return hashlib.sha256(payload).hexdigest()

    @staticmethod
    @contextmanager
    def _configuration_lock(path: Path):
        """Serialize registry writers across CatchEtude processes."""
        lock_path = path.with_name(path.name + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock_stream:
            lock_stream.seek(0, os.SEEK_END)
            if lock_stream.tell() == 0:
                lock_stream.write(b"\\0")
                lock_stream.flush()
            lock_stream.seek(0)

            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_stream.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    lock_stream.seek(0)
                    msvcrt.locking(lock_stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _default_by_id():
        return {d["id"]:copy.deepcopy(d) for d in DEFAULT_DECISIONS}

    def _migrate_decision(self, raw):
        decision=copy.deepcopy(raw)
        decision_id=decision.get("id")
        default=self._default_by_id().get(decision_id)
        old_handler=decision.get("handler")
        if default:
            merged=copy.deepcopy(default)
            merged.update(decision)
            decision=merged
            if decision.get("name") == _LEGACY_NAMES.get(decision_id):
                decision.pop("name", None)
            if old_handler in _LEGACY_HANDLERS:
                decision["handler"]=_LEGACY_HANDLERS[old_handler]
                if decision.get("base_path")==_OLD_DEFAULT_PATHS.get(decision.get("id")):
                    decision["base_path"]=default["base_path"]
                for key in ("folder_contains","folder_fallback","behaviour_second_line","requires_internal","allow_create","allow_rename","allow_delete"):
                    if key in default:
                        decision[key]=default[key]

        # Previous registry versions represented OneDrive-backed folder lists
        # with "onedrive". The new model stores the actual path in base_path and
        # uses "filesystem" to indicate that its child folders are enumerated.
        if str(decision.get("folder_source", "")).strip().casefold() == "onedrive":
            decision["folder_source"] = "filesystem"

        return decision

    def load_config(self):
        self.load_error = None
        path=self.get_config_path()
        if not path.exists():
            self.decisions=copy.deepcopy(DEFAULT_DECISIONS)
            self.save_config()
            return
        try:
            with path.open("r",encoding="utf-8") as stream:
                data=json.load(stream)
            if not isinstance(data,dict) or not isinstance(data.get("decisions"),list):
                raise ValueError("Classification file must contain a decisions array")
            if not all(isinstance(d,dict) for d in data["decisions"]):
                raise ValueError("Every classification must be an object")
            migrated=[self._migrate_decision(d) for d in data["decisions"]]
            self.validate_decisions(migrated)
            self.decisions=sorted(migrated,key=lambda d:(d.get("order",0),d["id"]))
            if (
                data.get("schema_version") != self.SCHEMA_VERSION
                or migrated != data["decisions"]
            ):
                self.save_config()
        except Exception as exc:
            self.load_error = str(exc)
            logging.exception("Could not load %s; built-in classifications remain available",path)
            # Preserve a corrupt or recoverable file; never overwrite it on parse failure.
            self.decisions=copy.deepcopy(DEFAULT_DECISIONS)

    @classmethod
    def validate_decisions(cls,decisions):
        if not isinstance(decisions,list):
            raise ValueError("decisions must be a list")
        seen=set()
        handlers={"keep","linear_docs","move_to_subfolder"}
        years={"none","required"}
        second={None,"","character_metadata","last_file","overworld_metadata"}
        sources={"none","filesystem"}
        for d in decisions:
            if not isinstance(d,dict):
                raise ValueError("Each decision must be an object")
            ident=d.get("id")
            if isinstance(ident,bool) or not isinstance(ident,int) or ident<=0:
                raise ValueError("Decision IDs must be positive integers")
            if ident in seen:
                raise ValueError(f"Duplicate decision ID: {ident}")
            seen.add(ident)
            if not d.get("name_key") and not d.get("name"):
                raise ValueError(f"Decision {ident} requires name or name_key")
            if d.get("handler") not in handlers:
                raise ValueError(f"Unsupported handler for decision {ident}")
            if d.get("year_mode","none") not in years:
                raise ValueError(f"Invalid year_mode for decision {ident}")
            if d.get("folder_source","none") not in sources:
                raise ValueError(f"Invalid folder_source for decision {ident}")
            if d["handler"]=="move_to_subfolder" and not str(d.get("base_path") or "").strip():
                raise ValueError(f"Decision {ident} requires base_path")
            if d.get("folder_contains") is not None and not isinstance(d["folder_contains"],str):
                raise ValueError(f"folder_contains for decision {ident} must be a string")
            if d.get("behaviour_second_line") not in second:
                raise ValueError(f"Unsupported behaviour_second_line for decision {ident}")
            for flag in ("enabled","requires_internal","allow_create","allow_rename","allow_delete"):
                if flag in d and not isinstance(d[flag],bool):
                    raise ValueError(f"{flag} for decision {ident} must be boolean")

    def save_config(self, expected_fingerprint=_UNSET_FINGERPRINT) -> bool:
        """Persist decisions atomically, optionally rejecting stale editor state.

        The optional fingerprint protects a dialog that remained open while
        another process or editor changed the configuration file.
        Registry writers also share a sidecar OS-level lock.
        """
        self.last_save_error = None
        self.last_save_message = None
        temporary_path: Path | None = None
        try:
            self.validate_decisions(self.decisions)
            path = self.get_config_path()
            path.parent.mkdir(parents=True, exist_ok=True)

            with self._configuration_lock(path):
                current_fingerprint = self.get_config_fingerprint()
                if (
                    expected_fingerprint is not _UNSET_FINGERPRINT
                    and current_fingerprint != expected_fingerprint
                ):
                    self.last_save_error = "conflict"
                    self.last_save_message = "Classification configuration changed on disk."
                    return False

                file_descriptor, temporary_name = tempfile.mkstemp(
                    prefix=path.name + ".",
                    suffix=".tmp",
                    dir=str(path.parent),
                )
                temporary_path = Path(temporary_name)
                with os.fdopen(
                    file_descriptor, "w", encoding="utf-8", newline="\\n"
                ) as stream:
                    json.dump(
                        {
                            "schema_version": self.SCHEMA_VERSION,
                            "decisions": self.decisions,
                        },
                        stream,
                        indent=4,
                        ensure_ascii=False,
                    )
                    stream.write("\\n")
                    stream.flush()
                    os.fsync(stream.fileno())

                # Check again immediately before replacement. External editors
                # do not honor the sidecar lock, but this catches intervening edits.
                current_fingerprint = self.get_config_fingerprint()
                if (
                    expected_fingerprint is not _UNSET_FINGERPRINT
                    and current_fingerprint != expected_fingerprint
                ):
                    self.last_save_error = "conflict"
                    self.last_save_message = "Classification configuration changed on disk."
                    return False

                os.replace(temporary_path, path)
                temporary_path = None
            return True
        except Exception as exc:
            self.last_save_error = "io_error"
            self.last_save_message = str(exc)
            logging.exception("Failed to save classification configuration")
            return False
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    logging.warning(
                        "Could not remove temporary classification file %s",
                        temporary_path,
                    )

    def get_active_decisions(self):
        return sorted((d for d in self.decisions if d.get("enabled",True)),key=lambda d:(d.get("order",0),d["id"]))

    def get_decision(self,type_id):
        try:
            wanted=int(type_id)
        except (TypeError,ValueError):
            return None
        return next((d for d in self.decisions if d.get("id")==wanted),None)

    def get_decision_name(self,decision,lang="es",loc=None):
        name=decision.get("name")
        if isinstance(name,dict):
            return str(name.get(lang) or name.get("es") or decision.get("name_key") or "")
        if isinstance(name,str) and name.strip():
            return name.strip()
        key=decision.get("name_key")
        if key and loc is not None:
            return loc.get(key)
        return str(key or f"Decision {decision.get('id','')}")
