"""
Integration tests for CatchEtude Plugin Host and IPC functionality.
"""

import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QTimer, QEventLoop
from PyQt6.QtWidgets import QApplication

from plugin_api import PluginState, ServiceState
from plugin_manager import PluginManager


class TestPluginHostIntegration(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not QApplication.instance():
            cls.app = QApplication(sys.argv)
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.plugins_dir = self.test_dir / "plugins"
        self.plugins_dir.mkdir()

        self.mgr = PluginManager(plugins_dir=self.plugins_dir)

    def tearDown(self):
        self.mgr.shutdown()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _wait_condition(self, condition_func, timeout_ms=5000):
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(50)

        def check():
            if condition_func():
                timer.stop()
                loop.quit()

        timer.timeout.connect(check)
        timer.start()

        # Timeout failsafe
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()

    def test_plugin_lifecycle_ready_and_services(self):
        code = """# /// catch-etude-plugin
# [plugin]
# id = "test.lifecycle"
# name = "Lifecycle Test"
# version = "1.0.0"
# api_version = 1
# capabilities = ["background_task", "parallel_service"]
# events = ["app_started"]
# [[services]]
# id = "worker-svc"
# autostart = true
# restart_policy = "never"
# /// end catch-etude-plugin

def run_plugin(ctx):
    ctx.emit_ready()

def run_service(svc_id, ctx):
    ctx.emit_ready()
"""
        p = self.plugins_dir / "lifecycle.py"
        p.write_text(code, encoding="utf-8")

        self.mgr.discover()
        self.mgr.enable_plugin("test.lifecycle")

        # Wait for plugin to be RUNNING
        proc = self.mgr.processes["test.lifecycle"]
        self._wait_condition(lambda: proc.plugin.state == PluginState.RUNNING, timeout_ms=4000)

        self.assertEqual(proc.plugin.state, PluginState.RUNNING)

        # Wait for service to be RUNNING
        svc = proc.services.get("worker-svc")
        self.assertIsNotNone(svc)
        self._wait_condition(lambda: svc.state == ServiceState.RUNNING, timeout_ms=4000)
        self.assertEqual(svc.state, ServiceState.RUNNING)

        # Disable and check shutdown
        self.mgr.disable_plugin("test.lifecycle")
        self._wait_condition(lambda: proc.plugin.state in (PluginState.STOPPED, PluginState.DISABLED), timeout_ms=4000)
        self.assertIn(proc.plugin.state, (PluginState.STOPPED, PluginState.DISABLED))

    def test_plugin_missing_run_plugin_fails(self):
        code = """# /// catch-etude-plugin
# [plugin]
# id = "test.missing-func"
# name = "Missing Func"
# version = "1.0.0"
# api_version = 1
# capabilities = ["background_task"]
# events = []
# /// end catch-etude-plugin

# Missing run_plugin!
"""
        p = self.plugins_dir / "missing.py"
        p.write_text(code, encoding="utf-8")

        self.mgr.discover()
        self.mgr.enable_plugin("test.missing-func")

        proc = self.mgr.processes["test.missing-func"]
        self._wait_condition(lambda: proc.plugin.state == PluginState.FAILED, timeout_ms=4000)

        self.assertEqual(proc.plugin.state, PluginState.FAILED)


if __name__ == "__main__":
    unittest.main()
