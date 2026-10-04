"""
Unit tests for CatchEtude Plugin Registry, Manifest Parser, and API schema.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from plugin_api import (
    extract_manifest_toml,
    validate_manifest,
    parse_and_validate_plugin_file,
    PluginState,
)
from plugin_registry import PluginRegistry, DiscoveredPlugin


class TestPluginRegistryAndAPI(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp())
        self.plugins_dir = self.test_dir / "plugins"
        self.plugins_dir.mkdir()
        self.state_path = self.test_dir / "plugins-state.json"
        self.config_dir = self.test_dir / "plugins-config"
        self.config_dir.mkdir()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_plugin_file(self, filename: str, content: str) -> Path:
        p = self.plugins_dir / filename
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)
        return p

    def test_valid_manifest_extraction_and_parsing(self):
        code = """# /// catch-etude-plugin
# [plugin]
# id = "test.valid-plugin"
# name = "Test Valid Plugin"
# version = "1.0.0"
# api_version = 1
# capabilities = ["background_task", "event_listener"]
# events = ["app_started", "file_detected"]
# /// end catch-etude-plugin

print('hello plugin')
"""
        p = self._create_plugin_file("valid_plugin.py", code)
        manifest, err = parse_and_validate_plugin_file(str(p))
        self.assertIsNone(err)
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest["plugin"]["id"], "test.valid-plugin")
        self.assertEqual(manifest["plugin"]["name"], "Test Valid Plugin")

    def test_valid_pyw_file(self):
        code = """# /// catch-etude-plugin
# [plugin]
# id = "test.valid-pyw"
# name = "Test PYW"
# version = "0.1.0"
# api_version = 1
# capabilities = ["tray_action"]
# events = ["app_started"]
# [[tray_actions]]
# id = "act1"
# label = "Act 1"
# command = "cmd1"
# /// end catch-etude-plugin
"""
        p = self._create_plugin_file("valid_plugin.pyw", code)
        manifest, err = parse_and_validate_plugin_file(str(p))
        self.assertIsNone(err)
        self.assertIsNotNone(manifest)
        self.assertEqual(manifest["plugin"]["id"], "test.valid-pyw")

    def test_missing_delimiters(self):
        code = """# No delimiters here
# id = "test.invalid"
"""
        p = self._create_plugin_file("no_delims.py", code)
        manifest, err = parse_and_validate_plugin_file(str(p))
        self.assertIsNotNone(err)
        self.assertIn("delimiters not found", err)

    def test_invalid_toml(self):
        code = """# /// catch-etude-plugin
# [plugin
# id = invalid toml content ===
# /// end catch-etude-plugin
"""
        p = self._create_plugin_file("bad_toml.py", code)
        manifest, err = parse_and_validate_plugin_file(str(p))
        self.assertIsNotNone(err)
        self.assertIn("TOML", err)

    def test_invalid_id_format(self):
        code = """# /// catch-etude-plugin
# [plugin]
# id = "INVALID_ID!!"
# name = "Bad ID"
# version = "1.0.0"
# api_version = 1
# capabilities = []
# events = []
# /// end catch-etude-plugin
"""
        p = self._create_plugin_file("bad_id.py", code)
        manifest, err = parse_and_validate_plugin_file(str(p))
        self.assertIsNotNone(err)
        self.assertIn("Invalid plugin ID", err)

    def test_unknown_capability(self):
        code = """# /// catch-etude-plugin
# [plugin]
# id = "test.unknown-cap"
# name = "Bad Cap"
# version = "1.0.0"
# api_version = 1
# capabilities = ["magic_power"]
# events = []
# /// end catch-etude-plugin
"""
        p = self._create_plugin_file("bad_cap.py", code)
        manifest, err = parse_and_validate_plugin_file(str(p))
        self.assertIsNotNone(err)
        self.assertIn("Unknown capability", err)

    def test_discovery_ignores_dirs_and_non_python_files(self):
        (self.plugins_dir / "subdir").mkdir()
        self._create_plugin_file("notes.txt", "some text")

        code = """# /// catch-etude-plugin
# [plugin]
# id = "test.disc"
# name = "Discovered"
# version = "1.0.0"
# api_version = 1
# capabilities = []
# events = []
# /// end catch-etude-plugin
"""
        self._create_plugin_file("good.py", code)

        registry = PluginRegistry(self.plugins_dir, self.state_path, self.config_dir)
        discovered = registry.discover()
        self.assertEqual(len(discovered), 1)
        self.assertEqual(discovered[0].plugin_id, "test.disc")

    def test_duplicate_plugin_ids(self):
        code1 = """# /// catch-etude-plugin
# [plugin]
# id = "dup.id"
# name = "Plugin One"
# version = "1.0.0"
# api_version = 1
# capabilities = []
# events = []
# /// end catch-etude-plugin
"""
        code2 = """# /// catch-etude-plugin
# [plugin]
# id = "dup.id"
# name = "Plugin Two"
# version = "1.0.0"
# api_version = 1
# capabilities = []
# events = []
# /// end catch-etude-plugin
"""
        self._create_plugin_file("p1.py", code1)
        self._create_plugin_file("p2.py", code2)

        registry = PluginRegistry(self.plugins_dir, self.state_path, self.config_dir)
        discovered = registry.discover()
        self.assertEqual(len(discovered), 2)

        valid_count = sum(1 for p in discovered if p.state != PluginState.INVALID)
        invalid_count = sum(1 for p in discovered if p.state == PluginState.INVALID)
        self.assertEqual(valid_count, 1)
        self.assertEqual(invalid_count, 1)

    def test_state_persistence_and_config(self):
        code = """# /// catch-etude-plugin
# [plugin]
# id = "test.persist"
# name = "Persist"
# version = "1.0.0"
# api_version = 1
# capabilities = ["settings"]
# events = []
# [settings_schema]
# port = { type = "integer" }
# /// end catch-etude-plugin
"""
        self._create_plugin_file("persist.py", code)

        registry = PluginRegistry(self.plugins_dir, self.state_path, self.config_dir)
        registry.discover()

        # Initially disabled by default
        plugin = registry.plugins_by_id["test.persist"]
        self.assertFalse(plugin.is_enabled)
        self.assertEqual(plugin.state, PluginState.DISABLED)

        # Enable it
        registry.set_enabled("test.persist", True)
        self.assertTrue(plugin.is_enabled)

        # Config save & load
        saved_ok = registry.save_plugin_config("test.persist", {"port": 8080})
        self.assertTrue(saved_ok)
        loaded_cfg = registry.get_plugin_config("test.persist")
        self.assertEqual(loaded_cfg.get("port"), 8080)

        # Re-create registry instance to verify persistence from file
        new_registry = PluginRegistry(self.plugins_dir, self.state_path, self.config_dir)
        new_registry.discover()
        reloaded_plugin = new_registry.plugins_by_id["test.persist"]
        self.assertTrue(reloaded_plugin.is_enabled)


if __name__ == "__main__":
    unittest.main()
