# CatchEtude Plugin Development Guide

This directory contains templates and documentation for creating CatchEtude plugins.

## Architecture & Rules

- **Single File Unit**: Every plugin is a single `.py` or `.pyw` file located directly in the `<APP_DIR>/plugins` directory.
- **Embedded TOML Manifest**: Each plugin file MUST start within its first 200 lines with an embedded TOML header enclosed between `# /// catch-etude-plugin` and `# /// end catch-etude-plugin`.
- **Subprocess Isolation**: CatchEtude launches child processes via `plugin_runner.py`. Plugins must NOT directly instantiate main Qt application widgets or access CatchEtude internals (`MainWindow`, `StateManager`, etc.). All communication occurs via structured IPC (`QLocalSocket` JSON).
- **Security Notice**: Third-party plugins execute with the user's Windows user privileges. Always prompt users before enabling third-party scripts.

## Manifest Header Format

```toml
# /// catch-etude-plugin
# [plugin]
# id = "publisher.plugin-id"
# name = "Plugin Display Name"
# version = "1.0.0"
# api_version = 1
# capabilities = ["background_task", "event_listener", "tray_action", "settings", "parallel_service"]
# events = ["app_started", "app_stopping", "file_detected", "move_finished", "settings_changed"]
#
# [[tray_actions]]
# id = "action_id"
# label = "Display Label"
# command = "command_name"
#
# [[services]]
# id = "service-id"
# autostart = true
# restart_policy = "never"
#
# [settings_schema]
# my_option = { type = "boolean", default = true, title = "Enable Option" }
# /// end catch-etude-plugin
```

## Entry Point Requirements

1. **Main Plugin Entry**: Main plugin processes require `run_plugin(context)`.
2. **Parallel Service Entry**: Service subprocesses require `run_service(service_id, context)`.

Call `context.emit_ready()` once your setup is completed.

## AI Developer Instructions
When creating or modifying plugins for CatchEtude:
- Modify existing templates (`basic_plugin.py`, `service_plugin.pyw`) as reference.
- Do NOT invent unapproved capabilities, non-standard event names, or auxilliary subfolder packages.
- Ensure clean IPC communication using only supported `ctx.log()`, `ctx.emit_ready()`, and handlers.
