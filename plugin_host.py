"""
Plugin Process and IPC Host management module for CatchEtude.
"""

import json
import logging
import os
import sys
import uuid
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QObject, QProcess, QTimer, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

import config
from plugin_api import PluginState, ServiceState
from plugin_registry import DiscoveredPlugin, PluginRegistry

logger = logging.getLogger(__name__)


class HostIPCConnection(QObject):
    """Encapsulates a QLocalSocket connection between the host and a single child process."""

    def __init__(self, socket: QLocalSocket, parent=None):
        super().__init__(parent)
        self.socket = socket
        self.buffer = bytearray()
        self.token: Optional[str] = None
        self.mode: Optional[str] = None
        self.plugin_id: Optional[str] = None
        self.service_id: Optional[str] = None

        self.socket.readyRead.connect(self._on_ready_read)

    def send(self, msg_dict: Dict[str, Any]) -> None:
        try:
            data = (json.dumps(msg_dict) + "\n").encode("utf-8")
            if len(data) > 65536:
                logger.error("IPC message payload exceeds 64 KiB limit")
                return
            self.socket.write(data)
            self.socket.flush()
        except Exception as e:
            logger.error(f"Error sending message over IPC: {e}")

    def _on_ready_read(self) -> None:
        self.buffer.extend(self.socket.readAll().data())
        while b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
                self.parent()._handle_ipc_message(self, msg)
            except Exception as e:
                logger.error(f"Error parsing JSON from client: {e}")


class PluginServiceProcess(QObject):
    """Manages a parallel service subprocess for a plugin."""

    state_changed = pyqtSignal(str, str)  # service_id, new_state (ServiceState)

    def __init__(self, plugin_id: str, service_def: Dict[str, Any], file_path: str, parent=None):
        super().__init__(parent)
        self.plugin_id = plugin_id
        self.service_id = service_def["id"]
        self.autostart = service_def.get("autostart", True)
        self.file_path = file_path

        self.state = ServiceState.STOPPED
        self.process: Optional[QProcess] = None
        self.connection: Optional[HostIPCConnection] = None
        self.execution_token = str(uuid.uuid4())
        self.error_message: Optional[str] = None

        self.missed_heartbeats = 0

    def set_state(self, new_state: ServiceState):
        if self.state != new_state:
            self.state = new_state
            self.state_changed.emit(self.service_id, new_state.value)


class PluginProcess(QObject):
    """Manages the main subprocess and its sub-services for a plugin."""

    state_changed = pyqtSignal(str)  # new_state (PluginState)
    log_received = pyqtSignal(str, str, str)  # level, target (plugin or service), message
    error_occurred = pyqtSignal(str)

    def __init__(self, plugin: DiscoveredPlugin, registry: PluginRegistry, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.registry = registry

        self.process: Optional[QProcess] = None
        self.server: Optional[QLocalServer] = None
        self.connection: Optional[HostIPCConnection] = None
        self.server_name = f"catchetude_plugin_{plugin.plugin_id}_{uuid.uuid4().hex[:8]}"
        self.execution_token = str(uuid.uuid4())

        self.services: Dict[str, PluginServiceProcess] = {}
        for svc_def in plugin.services:
            svc_proc = PluginServiceProcess(plugin.plugin_id, svc_def, str(plugin.file_path), self)
            svc_proc.state_changed.connect(self._on_service_state_changed)
            self.services[svc_def["id"]] = svc_proc

        self.ready_timer = QTimer(self)
        self.ready_timer.setSingleShot(True)
        self.ready_timer.setInterval(5000)  # 5 second timeout
        self.ready_timer.timeout.connect(self._on_ready_timeout)

        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.setInterval(30000)  # 30 second interval
        self.heartbeat_timer.timeout.connect(self._on_heartbeat_tick)

        self.missed_heartbeats = 0
        self.requires_restart = False

    def set_state(self, new_state: PluginState, error_msg: Optional[str] = None):
        self.plugin.state = new_state
        if error_msg:
            self.plugin.error_message = error_msg
        self.state_changed.emit(new_state.value)

    def start(self):
        if self.plugin.state in (PluginState.RUNNING, PluginState.STARTING):
            return

        self.set_state(PluginState.STARTING)
        self.missed_heartbeats = 0

        # Create IPC server
        self.server = QLocalServer(self)
        QLocalServer.removeServer(self.server_name)
        if not self.server.listen(self.server_name):
            err = f"Failed to listen on QLocalServer {self.server_name}"
            logger.error(f"[Plugin:{self.plugin.plugin_id}] {err}")
            self.set_state(PluginState.FAILED, err)
            return

        self.server.newConnection.connect(self._on_new_connection)

        # Launch main plugin runner process using pythonw or python
        python_exe = sys.executable
        runner_script = os.path.join(config.APP_DIR, "plugin_runner.py")

        args = [
            runner_script,
            "--mode", "plugin",
            "--file", str(self.plugin.file_path),
            "--socket", self.server_name,
            "--token", self.execution_token,
            "--plugin-id", self.plugin.plugin_id,
        ]

        self.process = QProcess(self)
        self.process.finished.connect(self._on_process_finished)
        self.process.errorOccurred.connect(self._on_process_error)
        self.process.start(python_exe, args)

        self.ready_timer.start()

    def _on_new_connection(self):
        while self.server and self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            conn = HostIPCConnection(socket, self)

    def _handle_ipc_message(self, conn: HostIPCConnection, msg: Dict[str, Any]):
        cmd = msg.get("cmd")

        if cmd == "init":
            token = msg.get("token")
            mode = msg.get("mode")
            service_id = msg.get("service_id")

            if mode == "plugin" and token == self.execution_token:
                conn.token = token
                conn.mode = mode
                conn.plugin_id = self.plugin.plugin_id
                self.connection = conn

                # Send initial configuration
                cfg = self.registry.get_plugin_config(self.plugin.plugin_id)
                conn.send({"cmd": "init_config", "config": cfg})

            elif mode == "service" and service_id in self.services:
                svc = self.services[service_id]
                if token == svc.execution_token:
                    conn.token = token
                    conn.mode = mode
                    conn.plugin_id = self.plugin.plugin_id
                    conn.service_id = service_id
                    svc.connection = conn

                    cfg = self.registry.get_plugin_config(self.plugin.plugin_id)
                    conn.send({"cmd": "init_config", "config": cfg})

        elif cmd == "ready":
            if conn.mode == "plugin" and conn == self.connection:
                self.ready_timer.stop()
                self.set_state(PluginState.RUNNING)
                self.heartbeat_timer.start()
                logger.info(f"[Plugin:{self.plugin.plugin_id}] Process ready")

                # Auto-start services
                for svc in self.services.values():
                    if svc.autostart:
                        self.start_service(svc.service_id)

            elif conn.mode == "service" and conn.service_id in self.services:
                svc = self.services[conn.service_id]
                svc.set_state(ServiceState.RUNNING)
                logger.info(f"[Plugin:{self.plugin.plugin_id}/Service:{svc.service_id}] Service ready")

        elif cmd == "heartbeat":
            if conn.mode == "plugin":
                self.missed_heartbeats = 0
            elif conn.mode == "service" and conn.service_id in self.services:
                self.services[conn.service_id].missed_heartbeats = 0

        elif cmd == "log":
            level = msg.get("level", "INFO")
            message = msg.get("message", "")
            target = f"Plugin:{self.plugin.plugin_id}"
            if conn.mode == "service" and conn.service_id:
                target = f"Plugin:{self.plugin.plugin_id}/Service:{conn.service_id}"
            self.log_received.emit(level, target, message)

        elif cmd == "error":
            err_msg = msg.get("message", "Unknown error")
            tb = msg.get("traceback", "")
            target = f"[Plugin:{self.plugin.plugin_id}]"
            if conn.mode == "service" and conn.service_id:
                target = f"[Plugin:{self.plugin.plugin_id}/Service:{conn.service_id}]"
            full_err = f"{target} {err_msg}\n{tb}".strip()
            logger.error(full_err)
            self.error_occurred.emit(full_err)

        elif cmd == "stopped":
            if conn.mode == "plugin":
                self.set_state(PluginState.STOPPED)
            elif conn.mode == "service" and conn.service_id in self.services:
                self.services[conn.service_id].set_state(ServiceState.STOPPED)

    def _on_ready_timeout(self):
        err = "Timeout waiting for ready signal (5s)"
        logger.error(f"[Plugin:{self.plugin.plugin_id}] {err}")
        self.stop(reason=err)
        self.set_state(PluginState.FAILED, err)

    def _on_heartbeat_tick(self):
        # Check main process heartbeat
        if self.plugin.state == PluginState.RUNNING:
            self.missed_heartbeats += 1
            if self.missed_heartbeats >= 2:
                err = "Heartbeat lost (2 intervals missed)"
                logger.error(f"[Plugin:{self.plugin.plugin_id}] {err}")
                self.stop(reason=err)
                self.set_state(PluginState.FAILED, err)
                return
            if self.connection:
                self.connection.send({"cmd": "heartbeat_req"})

        # Check services heartbeat
        for svc in self.services.values():
            if svc.state == ServiceState.RUNNING:
                svc.missed_heartbeats += 1
                if svc.missed_heartbeats >= 2:
                    err = f"Service '{svc.service_id}' heartbeat lost"
                    logger.error(f"[Plugin:{self.plugin.plugin_id}/Service:{svc.service_id}] {err}")
                    self.stop_service(svc.service_id)
                    svc.set_state(ServiceState.FAILED)
                elif svc.connection:
                    svc.connection.send({"cmd": "heartbeat_req"})

    def start_service(self, service_id: str):
        svc = self.services.get(service_id)
        if not svc or self.plugin.state != PluginState.RUNNING:
            return

        if svc.state in (ServiceState.RUNNING, ServiceState.STARTING):
            return

        svc.set_state(ServiceState.STARTING)
        svc.missed_heartbeats = 0
        svc.execution_token = str(uuid.uuid4())

        python_exe = sys.executable
        runner_script = os.path.join(config.APP_DIR, "plugin_runner.py")

        args = [
            runner_script,
            "--mode", "service",
            "--file", str(self.plugin.file_path),
            "--socket", self.server_name,
            "--token", svc.execution_token,
            "--plugin-id", self.plugin.plugin_id,
            "--service-id", service_id,
        ]

        svc.process = QProcess(self)
        svc.process.finished.connect(lambda exit_code, status, s_id=service_id: self._on_service_finished(s_id, exit_code))
        svc.process.start(python_exe, args)

    def stop_service(self, service_id: str):
        svc = self.services.get(service_id)
        if not svc or svc.state == ServiceState.STOPPED:
            return

        svc.set_state(ServiceState.STOPPING)
        if svc.connection:
            svc.connection.send({"cmd": "stop"})

        if svc.process and svc.process.state() != QProcess.ProcessState.NotRunning:
            if not svc.process.waitForFinished(1000):
                svc.process.kill()

        svc.set_state(ServiceState.STOPPED)

    def _on_service_finished(self, service_id: str, exit_code: int):
        svc = self.services.get(service_id)
        if svc and svc.state != ServiceState.STOPPED:
            if exit_code != 0:
                svc.set_state(ServiceState.FAILED)
            else:
                svc.set_state(ServiceState.STOPPED)

    def stop(self, reason: Optional[str] = None):
        self.ready_timer.stop()
        self.heartbeat_timer.stop()

        # Stop services first
        for svc_id in list(self.services.keys()):
            self.stop_service(svc_id)

        if self.plugin.state not in (PluginState.STOPPED, PluginState.FAILED, PluginState.DISABLED):
            self.set_state(PluginState.STOPPING)

        if self.connection:
            self.connection.send({"cmd": "stop"})

        if self.process and self.process.state() != QProcess.ProcessState.NotRunning:
            if not self.process.waitForFinished(2000):
                self.process.kill()

        if self.server:
            self.server.close()
            QLocalServer.removeServer(self.server_name)
            self.server = None

        if self.plugin.state != PluginState.FAILED:
            if self.plugin.is_enabled:
                self.set_state(PluginState.STOPPED)
            else:
                self.set_state(PluginState.DISABLED)

    def send_event(self, event_name: str, data: Dict[str, Any]):
        if self.plugin.state == PluginState.RUNNING and event_name in self.plugin.events:
            if self.connection:
                self.connection.send({"cmd": "event", "event": event_name, "data": data})

    def send_command(self, command: str, args: Dict[str, Any] = None):
        if self.plugin.state == PluginState.RUNNING and self.connection:
            self.connection.send({"cmd": "command", "command": command, "args": args or {}})

    def send_settings_changed(self, new_config: Dict[str, Any]):
        if self.connection:
            self.connection.send({"cmd": "settings_changed", "config": new_config})
        for svc in self.services.values():
            if svc.connection:
                svc.connection.send({"cmd": "settings_changed", "config": new_config})

    def _on_service_state_changed(self, service_id: str, state: str):
        self.plugin.service_states[service_id] = ServiceState(state)

    def _on_process_finished(self, exit_code: int, exit_status):
        if self.plugin.state not in (PluginState.STOPPED, PluginState.DISABLED, PluginState.FAILED):
            if exit_code != 0:
                err = f"Process exited unexpectedly with code {exit_code}"
                logger.error(f"[Plugin:{self.plugin.plugin_id}] {err}")
                self.set_state(PluginState.FAILED, err)
            else:
                self.set_state(PluginState.STOPPED)

    def _on_process_error(self, error):
        if self.plugin.state not in (PluginState.STOPPED, PluginState.DISABLED, PluginState.FAILED):
            err = f"Process error: {error}"
            logger.error(f"[Plugin:{self.plugin.plugin_id}] {err}")
            self.set_state(PluginState.FAILED, err)
