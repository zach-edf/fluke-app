from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import inspect
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from fluke_app.workflow_catalog import load_workflow_catalog
from fluke_protocol import ProfileRegistry
from fluke_protocol.profiles.base import DeviceProfile
from fluke_protocol.profiles.fluke_376fc import Fluke376FCProfile


@dataclass(frozen=True, slots=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    module: str
    callable_name: str = "register_plugin"
    description: str = ""
    enabled: bool = True
    workflow_paths: tuple[str, ...] = ()
    fixture_paths: tuple[str, ...] = ()


@dataclass(slots=True)
class PluginRegistration:
    profiles: list[DeviceProfile] = field(default_factory=list)
    workflow_paths: list[Path] = field(default_factory=list)
    fixture_paths: list[Path] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class LoadedPlugin:
    manifest: PluginManifest
    root: Path
    profiles: tuple[DeviceProfile, ...]
    workflow_paths: tuple[Path, ...]
    fixture_paths: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class PluginBundle:
    plugins: tuple[LoadedPlugin, ...]
    profiles: tuple[DeviceProfile, ...]
    workflow_paths: tuple[Path, ...]
    fixture_paths: tuple[Path, ...]


def default_plugin_root() -> Path:
    return Path(__file__).resolve().parents[2] / "plugins"


def load_plugin_bundle(plugin_root: str | Path | None = None) -> PluginBundle:
    root = default_plugin_root() if plugin_root is None else Path(plugin_root)
    loaded: list[LoadedPlugin] = []
    if root.exists():
        for manifest_path in sorted(root.rglob("manifest.json")):
            loaded_plugin = _load_plugin(manifest_path)
            if loaded_plugin is not None:
                loaded.append(loaded_plugin)
    profiles = tuple(_builtin_profiles() + [profile for plugin in loaded for profile in plugin.profiles])
    workflow_paths = tuple(path for plugin in loaded for path in plugin.workflow_paths)
    fixture_paths = tuple(path for plugin in loaded for path in plugin.fixture_paths)
    return PluginBundle(
        plugins=tuple(loaded),
        profiles=profiles,
        workflow_paths=workflow_paths,
        fixture_paths=fixture_paths,
    )


def build_profile_registry(plugin_root: str | Path | None = None) -> ProfileRegistry:
    bundle = load_plugin_bundle(plugin_root=plugin_root)
    return ProfileRegistry(list(bundle.profiles))


def build_workflow_catalog(plugin_root: str | Path | None = None):
    bundle = load_plugin_bundle(plugin_root=plugin_root)
    return load_workflow_catalog(extra_paths=list(bundle.workflow_paths))


def _load_plugin(manifest_path: Path) -> LoadedPlugin | None:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = PluginManifest(
        plugin_id=str(payload["plugin_id"]),
        name=str(payload.get("name") or payload["plugin_id"]),
        version=str(payload.get("version") or "0.1.0"),
        module=str(payload["module"]),
        callable_name=str(payload.get("callable") or "register_plugin"),
        description=str(payload.get("description") or ""),
        enabled=bool(payload.get("enabled", True)),
        workflow_paths=tuple(str(item) for item in payload.get("workflow_paths", ())),
        fixture_paths=tuple(str(item) for item in payload.get("fixture_paths", ())),
    )
    if not manifest.enabled:
        return None

    root = manifest_path.parent
    module = _load_module(root / manifest.module, manifest.plugin_id)
    registration = _call_registration(module, manifest.callable_name, root)
    workflow_paths = [root / relative for relative in manifest.workflow_paths]
    workflow_paths.extend(registration.workflow_paths)
    fixture_paths = [root / relative for relative in manifest.fixture_paths]
    fixture_paths.extend(registration.fixture_paths)
    return LoadedPlugin(
        manifest=manifest,
        root=root,
        profiles=tuple(registration.profiles),
        workflow_paths=tuple(path for path in workflow_paths if path.exists()),
        fixture_paths=tuple(path for path in fixture_paths if path.exists()),
    )


def _load_module(path: Path, plugin_id: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"fluke_plugin_{plugin_id}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load plugin module {path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call_registration(module: ModuleType, callable_name: str, root: Path) -> PluginRegistration:
    register = getattr(module, callable_name, None)
    if register is None or not callable(register):
        raise RuntimeError(f"Plugin module {module.__name__!r} does not define callable {callable_name!r}.")
    if len(inspect.signature(register).parameters) == 0:
        result = register()
    else:
        result = register(root)
    if isinstance(result, PluginRegistration):
        return result
    if isinstance(result, dict):
        return PluginRegistration(
            profiles=list(result.get("profiles", [])),
            workflow_paths=[Path(item) for item in result.get("workflow_paths", [])],
            fixture_paths=[Path(item) for item in result.get("fixture_paths", [])],
        )
    if isinstance(result, list):
        return PluginRegistration(profiles=result)
    raise RuntimeError(f"Unexpected plugin registration payload from {module.__name__!r}.")


def _builtin_profiles() -> list[DeviceProfile]:
    return [Fluke376FCProfile()]
