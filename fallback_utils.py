"""
Fallback Utilities module - Helper functions for file operations and path resolution.
Módulo Fallback Utilities: funciones de ayuda para operaciones de archivos y resolución de rutas.

This module provides logic for determining where files should be moved based on
classification rules and handles safety moves to the conflicts folder.
Este módulo proporciona la lógica para determinar a dónde deben moverse los
archivos basándose en las reglas de clasificación y gestiona los movimientos
de seguridad a la carpeta de conflictos.
"""

import os
import sys
import shutil
import logging
from pathlib import Path
from datetime import datetime
import config
from utils import resolve_duplicate, sanitize_windows_filename, setctime_blocking


def safe_move_to_conflicts(p: Path):
    """
    Safely moves a file to the conflicts folder in case of errors or 'keep' decision.
    Mueve un archivo de forma segura a la carpeta de conflictos en caso de errores o decisión 'keep'.
    """
    if not p.exists():
        return

    try:
        dest = resolve_duplicate(config.CONFLICTS / p.name)
        stat = p.stat()
        ctime = getattr(stat, "st_birthtime", stat.st_ctime)
        
        shutil.copy2(p, dest)
        setctime_blocking(dest, ctime)
        p.unlink(missing_ok=True)
            
        if p.exists():
            logging.critical(f"Source not removed after safe move: {p}")
            return
            
        logging.info(f"Safely moved to conflictos: {dest}")
        
    except Exception:
        logging.exception("safe_move_to_conflicts failed")


def compute_destination(decision: dict, src: Path) -> Path:
    """Resolve destinations through the JSON classification registry."""
    from classification_registry import ClassificationRegistry
    from decision_dispatcher import DecisionDispatcher

    movement_type = decision.get("movement_type", 1)
    new_name = sanitize_windows_filename(
        decision.get("new_name") or Path(src).stem
    )
    try:
        registry = ClassificationRegistry()
        definition = registry.get_decision(movement_type)
        if definition is None:
            raise ValueError(
                f"No classification definition exists for ID {movement_type!r}"
            )
        dispatcher = DecisionDispatcher(registry=registry)
        return dispatcher.resolve_destination(
            definition,
            Path(src),
            year=decision.get("year"),
            subfolder=decision.get("sub"),
            new_name=new_name,
        )
    except Exception:
        logging.exception(
            "Could not resolve destination for classification %r; "
            "using Conflicts as a safety fallback",
            movement_type,
        )
        return config.CONFLICTS / f"{new_name}{Path(src).suffix}"
