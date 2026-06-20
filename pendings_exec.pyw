# pendings_exec.pyw
"""
Envía 1 carpeta por ejecución a CatchEtude desde un TXT.
- Usa siempre la primera línea válida
- Si la carpeta está vacía, la elimina del TXT
- Si se envía correctamente, también se elimina
- este modulo esta dedicado a enviar carpetas pendientes a catchetude
"""
import os
from pathlib import Path
import sys
import json
from datetime import datetime
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtNetwork import QLocalSocket

TXT_PATH = (Path(__file__).resolve().parent / "pendings_hands.txt").as_posix()
SERVER_NAME = "CatchEtudeCommandServer"

# ⚠️ ADVERTENCIA DE ACTIVAR ESTO --------------------------------------------------
USE_DECK_MODE = True
# Si usted activa esto y es viernes, sabado y domingo o lunes
# Debera tener cuidado con el contenido que CatchEtude
# No debe desactivar bajo ninguna circunstancia el hide secure
# ----------------------------------------------------------------------------------

DECK_DIR = Path(__file__).resolve().parent / "deck"
ALARM_MP3 = Path(__file__).resolve().parent / "assets" / "alarm.mp3"

def get_years_for_today():
    """
    Monday=0 ... Sunday=6
    """
    weekday = datetime.now().weekday()

    mapping = {
        0: ["2026", "2025", "2018", "2017"],  # lunes
        1: ["2024"],                          # martes
        2: ["2023"],                          # miércoles
        3: ["2022"],                          # jueves
        4: ["2021"],                          # viernes
        5: ["2020"],                          # sábado
        6: ["2019"],                          # domingo
    }

    return mapping[weekday]

def is_dir_empty(path: str) -> bool:
    try:
        with os.scandir(path) as it:
            return not any(it)
    except FileNotFoundError:
        return True

def read_txt_lines(txt_path):
    if not txt_path.exists():
        return []

    with open(txt_path, "r", encoding="utf-8") as f:
        return [x.strip() for x in f if x.strip()]

def find_first_valid_in_year(year):
    txt = DECK_DIR / f"{year}.txt"

    for path in read_txt_lines(txt):

        if not os.path.isdir(path):
            continue

        if is_dir_empty(path):
            continue

        return path

    return None

def get_pending_path():
    years = get_years_for_today()

    # Lógica especial del lunes
    if datetime.now().weekday() == 0:

        for year in ["2026", "2025"]:
            path = find_first_valid_in_year(year)

            if path:
                return year, path

        for year in ["2018", "2017"]:
            path = find_first_valid_in_year(year)

            if path:
                return year, path

        return None, None

    # resto de días
    year = years[0]
    path = find_first_valid_in_year(year)

    return year, path

def play_alarm():
    try:
        from playsound import playsound
        playsound(str(ALARM_MP3))
    except Exception as e:
        print(f"No se pudo reproducir alarma: {e}")
        


def send_command(path: str, hide_secure: bool = True) -> bool:
    app = QCoreApplication(sys.argv)
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)

    if not socket.waitForConnected(3000):
        print(f"No se pudo conectar a {SERVER_NAME}: {socket.errorString()}")
        return False

    data = {
        "path": path,
        "hide_secure": hide_secure
    }

    socket.write(json.dumps(data).encode("utf-8"))
    ok = socket.waitForBytesWritten(3000)
    socket.disconnectFromServer()

    if ok:
        print(f"Enviado: {path}")
    return ok


def main():
    
    if USE_DECK_MODE:
        
        year, path = get_pending_path()

        if not path:
            print("No hay carpetas pendientes")
            return

        if year in {"2021", "2020", "2019", "2018", "2017"}:
            print("Reproduciendo alarma...")
            play_alarm()
            print("Alarma finalizada.")

        send_command(path)
        
    else:
    
        if not os.path.isfile(TXT_PATH):
            print("TXT no encontrado")
            return

        with open(TXT_PATH, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]

        if not lines:
            print("TXT vacío")
            return

        remaining = lines.copy()

        for path in lines:
            if not os.path.isdir(path):
                print(f"Ruta inválida, eliminada: {path}")
                remaining.remove(path)
                continue
            
            if is_dir_empty(path):
                continue

            if send_command(path):
                # remaining.remove(path)
                pass
            break

        # reescribir TXT
        with open(TXT_PATH, "w", encoding="utf-8") as f:
            for p in remaining:
                f.write(p + "\n")


if __name__ == "__main__":
    main()