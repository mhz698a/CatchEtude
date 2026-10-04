# /// catch-etude-plugin
# [plugin]
# id = "example.service-sync"
# name = "Service Sync Plugin"
# version = "1.0.0"
# api_version = 1
# capabilities = ["background_task", "parallel_service"]
# events = ["app_started", "app_stopping"]
#
# [[services]]
# id = "periodic-worker"
# autostart = true
# restart_policy = "never"
# /// end catch-etude-plugin

"""
Service Plugin Template for CatchEtude.
Demonstrates declaring and executing a parallel service subprocess within a single file.
"""

from PyQt6.QtCore import QTimer


def run_plugin(ctx):
    ctx.log("INFO", "Service Sync parent plugin process starting up...")

    def on_stop():
        ctx.log("INFO", "Parent plugin stopping cleanly.")

    ctx.on_stop(on_stop)
    ctx.emit_ready()


def run_service(service_id, ctx):
    ctx.log("INFO", f"Parallel service process '{service_id}' starting up...")

    # Set up periodic worker timer
    timer = QTimer()
    timer.setInterval(10000)  # Every 10 seconds

    def do_work():
        ctx.log("INFO", f"Parallel service '{service_id}' executing periodic background check.")

    timer.timeout.connect(do_work)
    timer.start()

    def on_stop():
        timer.stop()
        ctx.log("INFO", f"Parallel service '{service_id}' stopping cleanly.")

    ctx.on_stop(on_stop)
    ctx.emit_ready()
