"""
Send a local command to a running CatchEtude instance.

The endpoint accepts an existing file or directory path. Directory requests
are scanned recursively; file requests enqueue only that file.

Usage:
    python send_command.py "C:/path/to/image.png" True
    python send_command.py "C:/path/to/folder" False
"""

import json
import sys
from pathlib import Path

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtNetwork import QLocalSocket


SERVER_NAME = "CatchEtudeCommandServer"
DEFAULT_TIMEOUT_MS = 3000


def send_command(path, hide_secure=True, timeout_ms=DEFAULT_TIMEOUT_MS):
    """Ask the running CatchEtude instance to enqueue one file or a folder."""
    if not isinstance(hide_secure, bool):
        print("hide_secure must be True or False.")
        return False

    try:
        target = Path(path).expanduser().resolve(strict=True)
    except (OSError, TypeError, ValueError) as exc:
        print(f"Invalid path: {exc}")
        return False

    if not target.is_file() and not target.is_dir():
        print(f"Path is not a file or directory: {target}")
        return False

    # QLocalSocket requires a Qt application object even though this client
    # uses its blocking wait methods instead of starting an event loop.
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(sys.argv[:1])

    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)

    if not socket.waitForConnected(timeout_ms):
        print(f"Could not connect to {SERVER_NAME}: {socket.errorString()}")
        return False

    request = {
        "cmd": "enqueue_path",
        "path": str(target),
        "hide_secure": hide_secure,
    }
    payload = (json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8")

    if socket.write(payload) != len(payload) or not socket.waitForBytesWritten(timeout_ms):
        print(f"Could not send command: {socket.errorString()}")
        socket.abort()
        return False

    response_data = bytearray()
    while b"\n" not in response_data:
        if not socket.waitForReadyRead(timeout_ms):
            break
        response_data.extend(socket.readAll().data())

    if b"\n" not in response_data:
        # Older CatchEtude versions process the path request but do not send
        # an acknowledgement. Keep the client usable with those versions.
        if socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            print(f"Command sent to legacy {SERVER_NAME}: {request}")
            return True

        print(f"No acknowledgement received from {SERVER_NAME}.")
        socket.disconnectFromServer()
        return False

    response_line = bytes(response_data).split(b"\n", 1)[0]
    socket.disconnectFromServer()

    try:
        response = json.loads(response_line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"Invalid response from CatchEtude: {exc}")
        return False

    if not response.get("ok"):
        print(
            f"CatchEtude rejected the command: "
            f"{response.get('error', 'unknown_error')} - "
            f"{response.get('message', 'No details provided.')}"
        )
        return False

    print(
        f"Accepted {response.get('kind', 'command')}: "
        f"{response.get('path', response.get('command', ''))}"
    )
    return True


if __name__ == "__main__":
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        print("Usage: python send_command.py <file_or_folder_path> [hide_secure=True|False]")
        sys.exit(1)

    hide_secure_arg = True
    if len(sys.argv) == 3:
        value = sys.argv[2].strip().lower()
        if value not in ("true", "false"):
            print("hide_secure must be True or False.")
            sys.exit(1)
        hide_secure_arg = value == "true"

    sys.exit(0 if send_command(sys.argv[1], hide_secure_arg) else 1)
