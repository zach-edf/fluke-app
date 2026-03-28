# Architecture Overview

The application follows a layered architecture so the CLI, desktop app, and SDK all depend on the same app services and domain models.

## Layers

### `packages/fluke_core`

Pure domain types:

- measurement and connection enums
- canonical `Reading`, `Session`, `SessionMarker`
- workflow definitions and run models
- statistics helpers

This layer should not depend on BLE, Qt, or SQLite.

### `packages/fluke_protocol`

Device profile and decoding layer:

- profile matching rules
- GATT notification expectations
- raw payload parsing into normalized readings

### `packages/fluke_ble`

Transport abstraction:

- `BleAdapter` protocol
- `BleakAdapter` implementation

### `packages/fluke_app`

Application orchestration:

- `DeviceManager`
- `SessionRecorder`
- workflow catalog and runner
- export services
- debug bundle generation

### `packages/fluke_store`

Persistence layer:

- SQLite schema
- repositories for devices, sessions, readings, markers, workflow runs, workflow step results

### Presentation

- `apps/cli`: scan, stream, log, export, plugins, fixtures, diagnostics
- `apps/desktop`: PySide6-based home/discovery/live/session/workflow/settings UI
- `packages/fluke_sdk`: Python API built on the same shared services

## Extension Boundary

The built-in 376 FC support remains first-class, but the repo now supports optional plugin discovery through `plugins/`.

Plugins can contribute:

- additional `DeviceProfile` implementations
- workflow JSON packs
- fixture directories

The desktop UI does not need code changes to show a newly added workflow pack or profile metadata.

## Methodology

The development strategy is:

1. Normalize protocol behavior into canonical readings.
2. Persist sessions and make exports reliable.
3. Expose the same behaviors through CLI, desktop, and SDK.
4. Add workflows and extensions only after the core capture path is solid.
5. Keep CI and local verification hardware-light using fake adapters and replay fixtures.
