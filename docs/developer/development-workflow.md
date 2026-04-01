# Development Workflow

This guide explains how to work in the repo as a contributor.

## Core Principle

The codebase is intentionally structured so protocol logic, persistence, workflows, desktop behavior, CLI behavior, and SDK behavior all share the same underlying services.

When adding or fixing behavior:

- prefer the shared layer first
- keep device-specific logic in profiles
- keep persistence behavior in the store/app layers
- keep CLI and desktop layers thin where possible

If a fix only exists in one surface and should really exist in all of them, it is probably being implemented at the wrong layer.

## Recommended Local Setup

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-full.txt
python -m pip install -e .
```

The full requirements set is the safest contributor default because it includes:

- desktop dependencies
- plotting dependencies
- CLI/runtime dependencies
- BLE runtime dependencies

## Common Entry Points

### Desktop app

```powershell
fluke-desktop
```

or:

```powershell
python -m apps.desktop.main
```

### CLI

```powershell
fluke --help
```

or:

```powershell
python -m apps.cli.main --help
```

## Repo Layout

High-level structure:

- `apps/cli`: command-line entry points and command handlers
- `apps/desktop`: PySide6 runtime, presenters, views, theme, widgets
- `packages/fluke_core`: domain models, enums, statistics, workflow types
- `packages/fluke_protocol`: device profiles and payload decoding
- `packages/fluke_ble`: BLE adapter abstraction and Bleak implementation
- `packages/fluke_app`: orchestration services such as device manager, recorder, workflows, export, debug bundle
- `packages/fluke_store`: SQLite schema and repositories
- `packages/fluke_sdk`: Python SDK
- `packages/fluke_testing`: fake adapters, replay tools, fixture helpers
- `plugins/`: optional extension boundary for profiles and workflow packs
- `workflows/`: built-in workflow JSON definitions
- `tests/unit`: current automated test suite

## Where To Put Changes

### `packages/fluke_core`

Put changes here when you are working on:

- enums
- canonical data models
- statistics helpers
- workflow domain models

This layer should stay free of BLE, Qt, and SQLite concerns.

### `packages/fluke_protocol`

Put changes here when you are working on:

- profile matching
- GATT notification expectations
- packet parsing
- conversion from raw bytes into canonical `Reading` objects

### `packages/fluke_ble`

Put changes here when you are working on:

- transport abstractions
- `BleakAdapter`
- BLE connection mechanics

### `packages/fluke_app`

Put changes here when you are working on:

- orchestration behavior
- session recording
- workflows
- export services
- debug bundle generation
- device manager interactions that should be shared across CLI, desktop, and SDK

### `packages/fluke_store`

Put changes here when you are working on:

- schema
- repositories
- path handling
- persistence mechanics

### `apps/cli`

Put changes here when you are working on:

- argument parsing
- user-facing terminal messaging
- command orchestration

Avoid moving shared business logic into CLI commands if it belongs in `fluke_app`.

### `apps/desktop`

Put changes here when you are working on:

- desktop tab layout
- presenter/viewmodel wiring
- QSS themes
- chart widget behavior
- desktop-only UX

For more detail, see [Desktop UI Architecture](desktop-ui-architecture.md).

### `plugins`

Use this boundary for:

- experimental profiles
- plugin-contributed workflows
- plugin-contributed fixture directories

See [Plugins Overview](../../plugins/README.md) and [New Device Profile Guide](new-device-profile.md).

## Common Contributor Tasks

### Fix a parser or reading normalization bug

Typical path:

1. update the profile or protocol layer
2. add or update a unit test
3. validate CLI/Desktop/SDK behavior if the visible output changes

### Fix session export behavior

Typical path:

1. update the shared export or store logic
2. add export-focused tests
3. check both CLI and desktop export flows if relevant

### Add or modify desktop UX

Typical path:

1. inspect `apps/desktop/views.py` for layout and signal wiring
2. inspect `apps/desktop/presenters.py` for state and behavior
3. inspect `apps/desktop/viewmodels.py` if new state is needed
4. update or add desktop tests

### Add a workflow

Options:

- add a JSON definition under `workflows/`
- add a plugin workflow directory
- create a workflow in the desktop GUI and verify the emitted JSON

For workflow semantics, see [Workflows Page Guide](../workflows-page.md).

### Add a device profile

Use [New Device Profile Guide](new-device-profile.md).

## Running During Development

### Desktop

```powershell
python -m apps.desktop.main
```

### CLI

```powershell
python -m apps.cli.main --help
```

### Quick command checks

```powershell
python -m apps.cli.main scan --help
python -m apps.cli.main workflow --help
python -m apps.cli.main sessions --help
```

## Development Methodology

The most useful contributor workflow in this repo is:

1. reproduce the behavior with the smallest possible surface
2. identify which shared layer actually owns the bug or feature
3. change that layer first
4. add or update tests
5. verify the affected user-facing surfaces
6. update docs when user-visible behavior changed

## Documentation Expectations

If you change any of the following, update docs in the same pass:

- CLI commands or flags
- desktop UI behavior
- workflow authoring or workflow runtime behavior
- database/export behavior
- plugin/developer extension behavior

Relevant docs hubs:

- [Documentation Hub](../README.md)
- [Developer Documentation](README.md)

## Related Guides

- [Testing Guide](testing-guide.md)
- [Desktop UI Architecture](desktop-ui-architecture.md)
- [Fixtures and Debug Bundles](fixtures-and-debug.md)
- [New Device Profile Guide](new-device-profile.md)
- [Architecture Overview](../architecture.md)
