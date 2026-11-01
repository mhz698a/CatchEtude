# Sanitizacion de nombres para windows
import re

INVALID_WIN_CHARS = r'<>:"/\\|?*'

def sanitize_windows_filename(name: str, replacement: str = " ") -> str:
    """
    Sanitiza un nombre de archivo para Windows:
    - Elimina caracteres inválidos
    - Normaliza espacios
    - Quita espacios/puntos finales
    - Evita nombres vacíos o ilegales
    """
    if not name:
        return ""

    # Reemplazar caracteres inválidos
    for ch in INVALID_WIN_CHARS:
        name = name.replace(ch, replacement)

    # Eliminar caracteres de control
    name = "".join(c for c in name if ord(c) >= 32)

    # Normalizar espacios
    name = re.sub(r"\s+", " ", name)

    # Quitar espacios y puntos finales (Windows no los acepta)
    name = name.rstrip(" .")

    # Evitar nombres reservados
    if name in ("", ".", ".."):
        name = "file"

    return name