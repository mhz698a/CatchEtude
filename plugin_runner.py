"""
Plugin Runner for CatchEtude plugins.
Executed as an isolated process by PluginHost.
"""

import argparse
import importlib.util
import json
import logging
import os
import sys
import traceback
from typing import Any, Dict

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer, QObject, pyqtSlot
from PyQt6.QtNetwork import QLocalSocket


class PluginContext(QObject):
    """Execution context exposed to plugin code."""

    def __init__(self, mode: str, plugin_id: str, service_id: str, socket_name: str, token: str):
        super().__init__()
        self.mode = mode
        self.plugin_id = plugin_id
        self.service_id = service_id
        self.socket_name = socket_name
        self.token = token
        self.socket = QLocalSocket()
        self.buffer = bytearray()
        self.is_ready = False
        self.config: Dict[str, Any] = {}

        self.event_handlers = {}
        self.command_handlers = {}
        self.settings_handler = None
        self.stop_handler = None

    def connect_ipc(self) -> bool:
        self.socket.connectToServer(self.socket_name)
        if not self.socket.waitForConnected(3000):
            sys.stderr.write(f"Failed to connect to IPC server {self.socket_name}\n")
            return False

        self.socket.readyRead.connect(self._on_ready_read)
        self.socket.disconnected.connect(self._on_disconnected)

        # Send initial registration token message
        init_msg = {
            "cmd": "init",
            "token": self.token,
            "mode": self.mode,
            "plugin_id": self.plugin_id,
            "service_id": self.service_id,
        }
        self.send_ipc(init_msg)
        return True

    def send_ipc(self, msg_dict: Dict[str, Any]) -> None:
        try:
            data = (json.dumps(msg_dict) + "\n").encode("utf-8")
            if len(data) > 65536:
                sys.stderr.write("IPC message exceeds 64 KiB limit\n")
                return
            self.socket.write(data)
            self.socket.flush()
        except Exception as e:
            sys.stderr.write(f"Error sending IPC message: {e}\n")

    def emit_ready(self) -> None:
        self.is_ready = True
        self.send_ipc({"cmd": "ready"})

    def log(self, level: str, message: str) -> None:
        self.send_ipc({"cmd": "log", "level": level, "message": message})

    def emit_result(self, result_data: Dict[str, Any]) -> None:
        self.send_ipc({"cmd": "result", "data": result_data})

    def emit_error(self, message: str, traceback_str: str = "") -> None:
        self.send_ipc({"cmd": "error", "message": message, "traceback": traceback_str})

    def on_event(self, event_name: str, handler) -> None:
        self.event_handlers[event_name] = handler

    def on_command(self, command_name: str, handler) -> None:
        self.command_handlers[command_name] = handler

    def on_settings_changed(self, handler) -> None:
        self.settings_handler = handler

    def on_stop(self, handler) -> None:
        self.stop_handler = handler

    def _on_ready_read(self) -> None:
        self.buffer.extend(self.socket.readAll().data())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
                self._process_ipc_message(msg)
            except Exception as e:
                self.log("ERROR", f"Invalid JSON received from host: {e}")

    def _process_ipc_message(self, msg: Dict[str, Any]) -> None:
        cmd = msg.get("cmd")
        if cmd == "heartbeat_req":
            self.send_ipc({"cmd": "heartbeat"})
        elif cmd == "event":
            event_name = msg.get("event")
            data = msg.get("data", {})
            if event_name in self.event_handlers:
                try:
                    self.event_handlers[event_name](data)
                except Exception as e:
                    self.emit_error(f"Error in event handler '{event_name}': {e}", traceback.format_exc())
        elif cmd == "command":
            command_name = msg.get("command")
            args = msg.get("args", {})
            if command_name in self.command_handlers:
                try:
                    self.command_handlers[command_name](args)
                except Exception as e:
                    self.emit_error(f"Error in command handler '{command_name}': {e}", traceback.format_exc())
        elif cmd == "settings_changed":
            new_config = msg.get("config", {})
            self.config = new_config
            if self.settings_handler:
                try:
                    self.settings_handler(new_config)
                except Exception as e:
                    self.emit_error(f"Error in settings handler: {e}", traceback.format_exc())
        elif cmd == "init_config":
            self.config = msg.get("config", {})
        elif cmd == "stop":
            if self.stop_handler:
                try:
                    self.stop_handler()
                except Exception as e:
                    self.log("ERROR", f"Error in stop handler: {e}")
            self.send_ipc({"cmd": "stopped"})
            app = QApplication.instance()
            if app:
                app.quit()

    def _on_disconnected(self) -> None:
        app = QApplication.instance()
        if app:
            app.quit()


def main():
    parser = argparse.ArgumentParser(description="CatchEtude Plugin Runner")
    parser.add_argument("--mode", choices=["plugin", "service"], required=True)
    parser.add_argument("--file", required=True)
    parser.add_argument("--socket", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--plugin-id", required=True)
    parser.add_argument("--service-id", default="")
    args = parser.parse_args()

    file_path = os.path.abspath(args.file)
    if not os.path.exists(file_path):
        sys.stderr.write(f"Plugin file not found: {file_path}\n")
        sys.exit(1)

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    ctx = PluginContext(args.mode, args.plugin_id, args.service_id, args.socket, args.token)

    if not ctx.connect_ipc():
        sys.exit(1)

    # Dynamically import the plugin file
    try:
        module_name = f"catchetude_plugin_{args.plugin_id.replace('.', '_')}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            ctx.emit_error(f"Could not load module spec for {file_path}")
            sys.exit(1)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = mod
        spec.loader.exec_module(mod)
    except Exception as e:
        tb = traceback.format_exc()
        ctx.emit_error(f"Failed to import plugin file: {e}", tb)
        ctx.send_ipc({"cmd": "stopped"})
        sys.exit(1)

    # Execute designated entry point
    try:
        if args.mode == "plugin":
            if not hasattr(mod, "run_plugin"):
                ctx.emit_error(f"Plugin file missing mandatory 'run_plugin(context)' function")
                sys.exit(1)
            mod.run_plugin(ctx)
        elif args.mode == "service":
            if not hasattr(mod, "run_service"):
                ctx.emit_error(f"Plugin file missing mandatory 'run_service(service_id, context)' function")
                sys.exit(1)
            mod.run_service(args.service_id, ctx)
    except Exception as e:
        tb = traceback.format_exc()
        ctx.emit_error(f"Unhandled exception in plugin execution: {e}", tb)
        sys.exit(1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
