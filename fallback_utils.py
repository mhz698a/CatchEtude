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

from config import (
    CONFLICTS, BASE_INTERNAL, ONEDRIVE_DOCS, ONEDRIVE_DOCTOS_FAMILIA,
    IMAGES_FOLDER, MUSIC_FOLDER, OVERWORLD_FOLDER, ACROBAT_FOLDER
)
from utils import sha256_file, resolve_duplicate, sanitize_windows_filename, setctime_blocking


def safe_move_to_conflicts(p: Path):
    """
    Safely moves a file to the conflicts folder in case of errors or 'keep' decision.
    Mueve un archivo de forma segura a la carpeta de conflictos en caso de errores o decisión 'keep'.
    """
    if not p.exists():
        return

    try:
        dest = resolve_duplicate(CONFLICTS / p.name)
        stat = p.stat()
        ctime = getattr(stat, "st_birthtime", stat.st_ctime)
        
        shutil.copy2(p, dest)
        if sha256_file(p) == sha256_file(dest):
            setctime_blocking(dest, ctime)
            p.unlink(missing_ok=True)
            
        if p.exists():
            logging.critical(f"Source not removed after safe move: {p}")
            return
            
        logging.info(f"Safely moved to conflictos: {dest}")
        
    except Exception:
        logging.exception("safe_move_to_conflicts failed")


def compute_destination(decision: dict, src: Path) -> Path:
    """
    Computes the final destination path based on the user's decision.
    Calcula la ruta de destino final basada en la decisión del usuario.
    """
    movement_type = decision.get('movement_type', 1)
    year = decision.get('year', None)
    sub = decision.get('sub', None)
    newname = decision.get('new_name', src.stem)
    ext = src.suffix
    
    # Sanitize the new name
    newname = sanitize_windows_filename(newname)
    final = newname + ext
    
    # Check internal storage availability for dependent types
    if movement_type in (2, 3, 4, 7, 8) and not BASE_INTERNAL.exists():
        logging.error("BASE_INTERNAL not available in compute_destination")
        return CONFLICTS / final
    
    if movement_type == 1: # Keep in Downloads (actually moved to conflicts for tracking)
        return CONFLICTS / final
    
    if movement_type == 2: # Characters and Screenshots
        prefix = f"{year - 2003:02d}"
        year_dir = BASE_INTERNAL / str(year)
        target = None
        if year_dir.exists() and year_dir.is_dir():
            for child in sorted(year_dir.iterdir()):
                if child.is_dir():
                    name = child.name.lower()
                    if (prefix in name and IMAGES_FOLDER in name) or (IMAGES_FOLDER in name):
                        target = child
                        break
        if target is None:
            target = year_dir / f"{prefix}. {IMAGES_FOLDER}"
        dest_dir = (target / sub) if sub else target
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir / final
    
    if movement_type == 3: # Episodes
        year_dir = BASE_INTERNAL / str(year)
        target = None
        if year_dir.exists() and year_dir.is_dir():
            for child in sorted(year_dir.iterdir()):
                if child.is_dir() and '___[' in child.name:
                    target = child
                    break
        if target is None:
            target = year_dir
        dest_dir = (target / sub) if sub else target
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir / final
    
    if movement_type == 4: # Music
        prefix = f"{year - 2003:02d}"
        year_dir = BASE_INTERNAL / str(year)
        target = None
        if year_dir.exists() and year_dir.is_dir():
            for child in sorted(year_dir.iterdir()):
                if child.is_dir():
                    name = child.name.lower()
                    if (prefix in name and MUSIC_FOLDER in name) or (MUSIC_FOLDER in name):
                        target = child
                        break
        if target is None:
            target = year_dir / f"{prefix}. {MUSIC_FOLDER}"
        dest_dir = (target / sub) if sub else target
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir / final
    
    if movement_type == 5: # Academic (OneDrive)
        dest_dir = (ONEDRIVE_DOCS / sub) if sub else ONEDRIVE_DOCS
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir / final
        
    if movement_type == 6: # Family and Procedures (OneDrive)
        dest_dir = (ONEDRIVE_DOCTOS_FAMILIA / sub) if sub else ONEDRIVE_DOCTOS_FAMILIA
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir / final
    
    if movement_type == 7: # Linear Documentation
        dt = datetime.fromtimestamp(src.stat().st_mtime)        
        target_year = dt.year
        base_year_folder = BASE_INTERNAL / str(target_year)
        if not base_year_folder.exists():
            target_year = datetime.now().year
            base_year_folder = BASE_INTERNAL / str(target_year)
        
        prefix = f"{target_year - 2003:02d}"
        base = base_year_folder / f"{prefix}. {ACROBAT_FOLDER}"
        month_folder = dt.strftime("%Y-%m")
        dest_dir = base / month_folder
        dest_dir.mkdir(parents=True, exist_ok=True)        
        return dest_dir / final
    
    if movement_type == 8: # Overworld
        prefix = f"{year - 2003:02d}"
        year_dir = BASE_INTERNAL / str(year)
        target = None
        if year_dir.exists() and year_dir.is_dir():
            for child in sorted(year_dir.iterdir()):
                if child.is_dir():
                    name = child.name.lower()
                    if (prefix in name and OVERWORLD_FOLDER in name) or (OVERWORLD_FOLDER in name):
                        target = child
                        break
        if target is None:
            target = year_dir / f"{prefix}. {OVERWORLD_FOLDER}"
        dest_dir = (target / sub) if sub else target
        dest_dir.mkdir(parents=True, exist_ok=True)
        return dest_dir / final
    
    return CONFLICTS / final
