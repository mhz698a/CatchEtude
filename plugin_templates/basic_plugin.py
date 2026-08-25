# /// catch-etude-plugin
# [plugin]
# id = "example.basic-notifier"
# name = "Basic Notifier Plugin"
# version = "1.0.0"
# api_version = 1
# capabilities = ["background_task", "event_listener", "tray_action", "settings"]
# events = ["app_started", "file_detected", "move_finished", "settings_changed"]
#
# [[tray_actions]]
# id = "say_hello"
# label = "Say Hello"
# command = "say_hello"
#
# [settings_schema]
# enable_notifications = { type = "boolean", default = true, title = "Enable Notifications" }
# prefix = { type = "string", default = "[Notify]", title = "Log Prefix" }
# /// end catch-etude-plugin

"""
Basic Plugin Template for CatchEtude.
Demonstrates event listening, tray action command handling, and dynamic settings.
"""

def run_plugin(ctx):
    # Log initialization message
    ctx.log("INFO", "Basic Notifier plugin starting up...")

    # Event Handlers
    def on_app_started(data):
        ctx.log("INFO", "App started notification received by basic plugin")

    def on_file_detected(data):
        prefix = ctx.config.get("prefix", "[Notify]")
        file_name = data.get("name", "Unknown")
        ctx.log("INFO", f"{prefix} File detected: {file_name}")

    def on_move_finished(data):
        prefix = ctx.config.get("prefix", "[Notify]")
        src = data.get("src", "")
        dst = data.get("dst", "")
        ctx.log("INFO", f"{prefix} Move completed: {src} -> {dst}")

    ctx.on_event("app_started", on_app_started)
    ctx.on_event("file_detected", on_file_detected)
    ctx.on_event("move_finished", on_move_finished)

    # Command Handler for tray action
    def on_say_hello(args):
        prefix = ctx.config.get("prefix", "[Notify]")
        ctx.log("INFO", f"{prefix} Hello from CatchEtude Basic Plugin!")

    ctx.on_command("say_hello", on_say_hello)

    # Settings changed handler
    def on_settings_changed(new_config):
        ctx.log("INFO", f"Settings updated: {new_config}")

    ctx.on_settings_changed(on_settings_changed)

    # Clean shutdown handler
    def on_stop():
        ctx.log("INFO", "Basic Notifier plugin stopping cleanly.")

    ctx.on_stop(on_stop)

    # Signal to CatchEtude host that setup is ready
    ctx.emit_ready()
