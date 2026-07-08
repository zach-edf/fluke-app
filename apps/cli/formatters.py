"""Shared formatters, JSON serializers, and argparse validators for the CLI."""

from __future__ import annotations

import argparse
import json
from typing import Any, Callable

from fluke_core.models.reading import Reading


# ---------------------------------------------------------------------------
# Reading formatters
# ---------------------------------------------------------------------------

def format_reading(reading: Reading) -> str:
    """Human-readable pipe-delimited reading line."""
    value = "-" if reading.value is None else f"{reading.value:.6g}"
    mode = reading.mode or "-"
    return (
        f"{reading.timestamp_utc.isoformat()} | "
        f"{reading.display_text or '-'} | "
        f"value={value} {reading.unit or ''}".rstrip()
        + f" | type={reading.measurement_type.value} | mode={mode} | status={reading.status.value}"
    )


def reading_to_dict(reading: Reading) -> dict[str, Any]:
    """JSON-serializable dict for a single reading."""
    return reading.as_dict()


# ---------------------------------------------------------------------------
# Device formatters
# ---------------------------------------------------------------------------

def format_device(device: object) -> str:
    """Human-readable multi-line device block (indented with leading dash)."""
    lines = [
        f"- name={getattr(device, 'nickname', None) or '(no name)'}",
        f"  id={device.device_id}",
        f"  rssi={device.rssi if device.rssi is not None else '-'}",
        f"  model={device.model_name}",
        f"  support={device.support_level}",
    ]
    if device.profile_id:
        lines.append(f"  profile={device.profile_id}")
    return "\n".join(lines)


def device_to_dict(device: object) -> dict[str, Any]:
    """JSON-serializable dict for a scanned device."""
    return {
        "device_id": device.device_id,
        "name": getattr(device, "nickname", None),
        "ble_address": getattr(device, "ble_address", ""),
        "model_name": device.model_name,
        "profile_id": device.profile_id,
        "support_level": device.support_level,
        "rssi": device.rssi,
        "capabilities": list(getattr(device, "capabilities", [])),
    }


# ---------------------------------------------------------------------------
# Session formatters
# ---------------------------------------------------------------------------

def format_session(session: object) -> str:
    """Human-readable single-line session summary."""
    ended = session.ended_at.isoformat() if session.ended_at else "-"
    title = session.title or "-"
    line = (
        f"- {session.session_id} | device={session.device_id} | "
        f"started={session.started_at.isoformat()} | ended={ended} | title={title}"
    )
    asset_id = getattr(session, "asset_id", None)
    if asset_id:
        line += f" | asset={asset_id}"
    return line


def session_to_dict(session: object) -> dict[str, Any]:
    """JSON-serializable dict for a session."""
    return {
        "session_id": session.session_id,
        "device_id": session.device_id,
        "started_at": session.started_at.isoformat(),
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "title": session.title,
        "notes": session.notes,
        "tags": list(getattr(session, "tags", [])),
        "app_version": getattr(session, "app_version", None),
        "profile_id": getattr(session, "profile_id", None),
        "asset_id": getattr(session, "asset_id", None),
    }


# ---------------------------------------------------------------------------
# Asset formatters
# ---------------------------------------------------------------------------

def format_asset(asset: object) -> str:
    """Human-readable single-line asset summary."""
    parts = [f"- {asset.asset_id} | name={asset.name}"]
    if asset.asset_type:
        parts.append(f"type={asset.asset_type}")
    if asset.location:
        parts.append(f"location={asset.location}")
    return " | ".join(parts)


def asset_to_dict(asset: object) -> dict[str, Any]:
    """JSON-serializable dict for an asset."""
    created_at = getattr(asset, "created_at", None)
    return {
        "asset_id": asset.asset_id,
        "name": asset.name,
        "asset_type": asset.asset_type,
        "location": asset.location,
        "notes": asset.notes,
        "created_at": created_at.isoformat() if created_at else None,
    }


# ---------------------------------------------------------------------------
# Profile formatters
# ---------------------------------------------------------------------------

def format_profile(profile: object) -> str:
    """Human-readable profile block."""
    capabilities = ", ".join(profile.capabilities())
    return f"- {profile.model_name} ({profile.profile_id})\n  capabilities={capabilities}"


def profile_to_dict(profile: object) -> dict[str, Any]:
    """JSON-serializable dict for a device profile."""
    return {
        "profile_id": profile.profile_id,
        "model_name": profile.model_name,
        "capabilities": list(profile.capabilities()),
    }


# ---------------------------------------------------------------------------
# Plugin formatters
# ---------------------------------------------------------------------------

def format_plugin(plugin: object) -> str:
    """Human-readable plugin block."""
    m = plugin.manifest
    lines = [f"- {m.name} ({m.plugin_id}) v{m.version}"]
    if m.description:
        lines.append(f"  description={m.description}")
    if plugin.profiles:
        lines.append(f"  profiles={', '.join(p.profile_id for p in plugin.profiles)}")
    if plugin.workflow_paths:
        lines.append(f"  workflow_paths={', '.join(str(p) for p in plugin.workflow_paths)}")
    if plugin.fixture_paths:
        lines.append(f"  fixture_paths={', '.join(str(p) for p in plugin.fixture_paths)}")
    return "\n".join(lines)


def plugin_to_dict(plugin: object) -> dict[str, Any]:
    """JSON-serializable dict for a loaded plugin."""
    m = plugin.manifest
    return {
        "plugin_id": m.plugin_id,
        "name": m.name,
        "version": m.version,
        "description": m.description,
        "profiles": [p.profile_id for p in plugin.profiles],
        "workflow_paths": [str(p) for p in plugin.workflow_paths],
        "fixture_paths": [str(p) for p in plugin.fixture_paths],
    }


# ---------------------------------------------------------------------------
# Generic list output (human vs JSON)
# ---------------------------------------------------------------------------

def output_list(
    items: list[Any],
    json_mode: bool,
    formatter: Callable[[Any], str],
    to_dict: Callable[[Any], dict[str, Any]],
) -> None:
    """Print a list of items as JSON or human-readable text."""
    if json_mode:
        print(json.dumps([to_dict(item) for item in items], indent=2))
    else:
        for item in items:
            print(formatter(item))


# ---------------------------------------------------------------------------
# Tag parsing
# ---------------------------------------------------------------------------

def parse_tags(raw: str) -> list[str]:
    """Split a comma-separated tag string into a clean list."""
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


# ---------------------------------------------------------------------------
# Argparse type validators
# ---------------------------------------------------------------------------

def positive_float(value: str) -> float:
    """Argparse type: float > 0."""
    fval = float(value)
    if fval <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive number, got {value}")
    return fval


def nonneg_float(value: str) -> float:
    """Argparse type: float >= 0."""
    fval = float(value)
    if fval < 0:
        raise argparse.ArgumentTypeError(f"must be a non-negative number, got {value}")
    return fval


def positive_int(value: str) -> int:
    """Argparse type: int > 0."""
    ival = int(value)
    if ival <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {value}")
    return ival


def nonneg_int(value: str) -> int:
    """Argparse type: int >= 0."""
    ival = int(value)
    if ival < 0:
        raise argparse.ArgumentTypeError(f"must be a non-negative integer, got {value}")
    return ival
