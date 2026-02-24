"""
Example script to send commands to CatchEtude using QLocalSocket.
Script de ejemplo para enviar comandos a CatchEtude usando QLocalSocket.

Usage:
python send_command.py "C:/path/to/folder_or_file" True
"""

import sys
import json
from PyQt6.QtCore import QCoreApplication
from PyQt6.QtNetwork import QLocalSocket

def send_command(path, hide_secure=True):
    app = QCoreApplication(sys.argv)
    socket = QLocalSocket()
    
    server_name = "CatchEtudeCommandServer"
    socket.connectToServer(server_name)
    
    if socket.waitForConnected(3000):
        data = {
            "path": path,
            "hide_secure": hide_secure
        }
        message = json.dumps(data).encode('utf-8')
        socket.write(message)
        socket.waitForBytesWritten(3000)
        socket.disconnectFromServer()
        print(f"Command sent: {data}")
    else:
        print(f"Could not connect to server {server_name}: {socket.errorString()}")
    
    # app.quit() is not needed since we don't start the event loop
    # but we need to exit the script.

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python send_command.py <path> [hide_secure=True|False]")
        sys.exit(1)
        
    path_arg = sys.argv[1]
    hide_secure_arg = True
    if len(sys.argv) > 2:
        hide_secure_arg = sys.argv[2].lower() == 'true'
        
    send_command(path_arg, hide_secure_arg)
