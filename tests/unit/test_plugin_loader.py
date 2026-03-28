from __future__ import annotations

from pathlib import Path
import unittest
from uuid import uuid4

from fluke_plugins import build_profile_registry, build_workflow_catalog, load_plugin_bundle


class PluginLoaderTests(unittest.TestCase):
    def test_loader_discovers_plugin_profiles_and_workflows(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        plugin_root = tmp / "plugins"
        plugin_dir = plugin_root / "example" / "demo_plugin"
        workflow_dir = plugin_dir / "workflows"
        fixture_dir = plugin_dir / "fixtures"
        workflow_dir.mkdir(parents=True, exist_ok=False)
        fixture_dir.mkdir(parents=True, exist_ok=False)

        (plugin_dir / "manifest.json").write_text(
            """
{
  "plugin_id": "demo_plugin",
  "name": "Demo Plugin",
  "version": "0.1.0",
  "module": "profile.py",
  "workflow_paths": ["workflows"],
  "fixture_paths": ["fixtures"]
}
""".strip(),
            encoding="utf-8",
        )
        (plugin_dir / "profile.py").write_text(
            """
from fluke_plugins.loader import PluginRegistration
from fluke_protocol.profiles.base import DeviceProfile


class DemoProfile(DeviceProfile):
    profile_id = "demo_profile"
    model_name = "Demo Meter"

    def matches(self, advertisement_name, metadata):
        return advertisement_name == "Demo Meter"

    def capabilities(self):
        return ["demo_capture"]

    def notification_characteristics(self):
        return ["0000demo-0000-1000-8000-00805f9b34fb"]

    def parse_notification(self, characteristic_uuid, payload, device_id, observed_at=None):
        return []


def register_plugin(plugin_root):
    return PluginRegistration(profiles=[DemoProfile()])
""".strip(),
            encoding="utf-8",
        )
        (workflow_dir / "demo_workflow.json").write_text(
            """
{
  "workflow_id": "demo_workflow_v1",
  "title": "Demo Workflow",
  "steps": [
    {
      "id": "demo_step",
      "instruction": "Run the demo step.",
      "capture": false
    }
  ]
}
""".strip(),
            encoding="utf-8",
        )

        bundle = load_plugin_bundle(plugin_root)
        registry = build_profile_registry(plugin_root)
        workflows = build_workflow_catalog(plugin_root)

        self.assertEqual(len(bundle.plugins), 1)
        self.assertEqual(bundle.plugins[0].manifest.plugin_id, "demo_plugin")
        self.assertIn("demo_profile", [profile.profile_id for profile in registry.all()])
        self.assertIsNotNone(workflows.get("demo_workflow_v1"))


if __name__ == "__main__":
    unittest.main()
