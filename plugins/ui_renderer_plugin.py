# /// catch-etude-plugin
# [plugin]
# id = "catchetude.ui-renderer"
# name = "UI Renderer Plugin"
# version = "1.0.0"
# api_version = 1
# capabilities = ["background_task", "tray_action"]
# events = []
#
# [[tray_actions]]
# id = "render_ui"
# label = "Renderizar Interfaz UI"
# command = "render_ui"
# /// end catch-etude-plugin

"""
UI Renderer Plugin for CatchEtude.
Captures the CatchEtude main window UI into an image file inside Downloads.
"""

import os
import json
import time
from pathlib import Path
from PyQt6.QtNetwork import QLocalSocket

def run_plugin(ctx):
    ctx.log("INFO", "UI Renderer plugin initialized.")

    def on_render_ui(args):
        ctx.log("INFO", "Command 'render_ui' received. Requesting main window snapshot...")
        try:
            socket = QLocalSocket()
            socket.connectToServer("CatchEtudeCommandServer")
            if socket.waitForConnected(1000):
                cmd_data = json.dumps({"cmd": "capture_ui_render"})
                socket.write(cmd_data.encode('utf-8'))
                socket.waitForBytesWritten(1000)
                socket.disconnectFromServer()
                ctx.log("INFO", "UI render capture request sent to main application.")
            else:
                ctx.log("ERROR", f"Could not connect to CatchEtudeCommandServer: {socket.errorString()}")
        except Exception as e:
            ctx.log("ERROR", f"Error requesting UI render capture: {e}")

    ctx.on_command("render_ui", on_render_ui)

    def on_stop():
        ctx.log("INFO", "UI Renderer plugin stopping.")

    ctx.on_stop(on_stop)
    ctx.emit_ready()
