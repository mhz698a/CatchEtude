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
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtNetwork import QLocalSocket

TXT_PATH = (Path(__file__).resolve().parent / "pendings_hands.txt").as_posix()
SERVER_NAME = "CatchEtudeCommandServer"

def is_dir_empty(path: str) -> bool:
    try:
        with os.scandir(path) as it:
            return not any(it)
    except FileNotFoundError:
        return True

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
        if not os.path.isdir(path) or is_dir_empty(path):
            print(f"Ruta vacía o inválida, eliminada: {path}")
            remaining.remove(path)
            continue

        if send_command(path):
            remaining.remove(path)
        break

    # reescribir TXT
    with open(TXT_PATH, "w", encoding="utf-8") as f:
        for p in remaining:
            f.write(p + "\n")


if __name__ == "__main__":
    main()