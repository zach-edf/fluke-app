# Fluke Community Desktop

Open desktop app, CLI, and Python SDK for working with BLE-enabled Fluke meters from a shared architecture.

The project started from a single reverse-engineered prototype in `fluke_ble.py`. The repo now contains a more structured codebase built around:

- canonical domain models
- profile-based protocol decoding
- shared application services
- SQLite session logging
- desktop and CLI surfaces on top of the same services
- guided workflow execution
- an extension boundary for future contributed profiles and workflow packs

The current in-tree device focus is still the Fluke 376 FC.

For a structured documentation set instead of this high-level overview, start with [docs/README.md](docs/README.md).

## Project Status

What exists now:

- BLE scan, connect, and stream path through shared services
- normalized `Reading` model and 376 FC profile decoder
- SQLite session, marker, workflow-run, and export support
- desktop app with discovery, live view, charting, replay, markers, session export, and workflow runner
  - live view supports rolling and derived chart modes without rewriting stored data
  - session replay filters mixed-mode sessions into cleaner measurement views without rewriting raw data
  - session replay supports elapsed-time, UTC, and per-segment chart axes
  - desktop session exports include raw CSV/JSON plus analysis CSV and segment-summary JSON
  - workflow steps support manual, stable-capture, countdown, and observe-and-confirm interaction modes
  - workflow run history can be reviewed and exported as reports from the desktop UI
- CLI for scan, stream, watch, alert, log, sessions, workflows, plugins, fixture capture, and debug bundle export
- Python SDK on the same core stack
- plugin loader for contributed profiles and workflow JSON packs
- hardware-free test coverage using fake BLE adapters and replay frames

What still needs repeated real-hardware validation:

- longer-duration BLE sessions on the rebuilt stack
- reconnect stability over longer sessions
- packaged installer behavior
- additional model support beyond the 376 FC

## Guiding Methodology

This repo intentionally avoids "desktop-only" or "CLI-only" logic.

The development order has been:

1. normalize protocol payloads into canonical readings
2. persist sessions and make exports reliable
3. expose the same behavior through CLI, desktop, and SDK
4. add charts, workflows, and contributor tooling only after the core path was solid

That methodology matters. If you add a new capability, add it to the shared stack first unless there is a very strong reason not to.

## Repository Map

```text
apps/
  cli/                  Command-line entry points
  desktop/              PySide6 desktop application
packages/
  fluke_app/            Shared orchestration services
  fluke_ble/            BLE transport abstraction + Bleak adapter
  fluke_core/           Domain models, enums, statistics, workflow models
  fluke_plugins/        Plugin discovery and extension loading
  fluke_protocol/       Device profile registry and protocol decoding
  fluke_sdk/            Public Python SDK
  fluke_store/          SQLite schema and repositories
  fluke_testing/        Fake adapters, replay tools, fixture capture helpers
plugins/
  examples/             Disabled template plugin for contributors
workflows/              Built-in workflow definitions
scripts/
  fixture_capture.py    Raw fixture capture helper
  export_debug_bundle.py
docs/
  README.md               Documentation hub
  architecture.md
  getting-started.md
  desktop-guide.md
  cli-guide.md
  data-and-exports.md
  sdk-guide.md
  workflows-page.md
  support-matrix.md
  developer/
```

## Requirements

- Python 3.11+
- BLE-capable host
- virtual environment recommended
- `bleak` for BLE runtime
- `PySide6` for the desktop UI

Minimal dependency set:

- `requirements.txt`: CLI + SDK + BLE runtime

Full contributor / desktop dependency set:

- `requirements-full.txt`: desktop, plotting, dashboard/data extras, plus the base BLE runtime

## Installation

### Full install (desktop + CLI + SDK)

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-full.txt
python -m pip install -e .
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-full.txt
python -m pip install -e .
```

### Minimal install (CLI + SDK only)

```bash
python -m pip install -r requirements.txt
python -m pip install -e .
```

The editable install provides these entry points from `pyproject.toml`:

- `fluke`
- `fluke-cli`
- `fluke-desktop`

If you skip `python -m pip install -e .`, use the module entry points directly:

- `python -m apps.cli.main`
- `python -m apps.desktop.main`

## Running The App

### CLI

Installed entry point:

```bash
fluke --help
```

Module fallback:

```bash
python -m apps.cli.main --help
```

Global flags:

- `--version`
- `-v` / `--verbose`
- `--json` for commands that support structured output

### Desktop

Installed entry point:

```bash
fluke-desktop
```

Module fallback:

```bash
python -m apps.desktop.main
```

On macOS, the desktop app uses `PySide6.QtAsyncio` for Qt/BLE event-loop integration. Other platforms continue to use the background async runner.

### Python SDK

Example:

```python
import asyncio

from fluke_sdk import FlukeClient


async def main() -> None:
    client = FlukeClient()
    devices = await client.scan(timeout_s=5.0)
    if not devices:
        print("No devices found.")
        return

    device = await client.connect(devices[0].device_id)
    print(device)

    async for reading in client.stream_readings():
        print(reading.display_text)
        break

    await client.close()


asyncio.run(main())
```

## CLI Quickstart

### 1. Scan for nearby devices

```bash
fluke scan --timeout 10 --name Fluke
```

### 2. Stream readings

Plain text stream:

```bash
fluke stream --device "<DEVICE_ID>" --profile fluke_376fc
```

Retro terminal dashboard:

```bash
fluke stream --device "<DEVICE_ID>" --profile fluke_376fc --dashboard
```

Additional live terminal views:

```bash
fluke watch --device "<DEVICE_ID>" --profile fluke_376fc
fluke alert --device "<DEVICE_ID>" --profile fluke_376fc --high 120
```

### 3. Log to SQLite and optionally export

```bash
fluke log \
  --device "<DEVICE_ID>" \
  --profile fluke_376fc \
  --duration 30 \
  --title "Bench run" \
  --notes "Initial validation" \
  --csv-output exports/session.csv \
  --json-output exports/session.json
```

### 4. Inspect recorded sessions

```bash
fluke sessions list
fluke sessions export --session "<SESSION_ID>" --format json --output exports/session.json
```

### 5. Browse or run workflows

```bash
fluke workflow list
fluke workflow run --workflow battery_pack_check_v1 --device "<DEVICE_ID>" --profile fluke_376fc
```

### 6. Structured output

The `--json` flag is global, so place it before the subcommand:

```bash
fluke --json devices supported
fluke --json scan --timeout 5
fluke --json sessions list
fluke --json workflow list
```

### 7. Plugins and diagnostics

```bash
fluke plugins list
fluke fixtures capture --device "<DEVICE_ID>" --profile fluke_376fc --duration 10 --output fixtures/capture.json
fluke debug bundle --output artifacts/debug-bundle.zip
```

### Default database path

When `--database` is omitted, commands use a platform-appropriate default path:

- macOS: `~/Library/Application Support/fluke-community/fluke.db`
- Linux: `~/.local/share/fluke-community/fluke.db`
- Windows: `%LOCALAPPDATA%/fluke-community/fluke.db`

The default path is resolved lazily, so commands such as `fluke --version` do not create directories or touch the database.

## Desktop Workflow

The desktop app currently includes:

- Home
- Device Discovery
- Live Reading
- Session
- Workflows
- Settings

### Live Reading

The Live Reading tab supports:

- current reading display
- unit and measurement type
- live chart
- chart mode selector
- min / max / avg / sample summary
- session start / stop
- manual session markers
- live chart PNG export

The live chart now keeps a larger timestamped buffer and derives the visible plot from the selected chart mode:

- `Rolling 30s`
- `Rolling 60s`
- `Rolling 5m`
- `Since mode start`
- `Since session start`

When the meter changes measurement context, the live view starts a new derived segment and shows a transient banner. Changing chart mode also starts a new `Since mode start` boundary instead of discarding buffered readings.

### Session

The Session tab supports:

- recent sessions
- replay chart
- measurement-view filtering for mixed-mode sessions
- axis mode selection for `Elapsed Time`, `UTC Timestamp`, and `By Segment`
- per-segment selection when viewing a derived segment axis
- marker review
- session notes
- `Export Raw CSV`
- `Export Raw JSON`
- `Export Analysis CSV`
- `Export Segment Summary JSON`
- chart PNG export

Replay filtering is derived in the UI layer rather than rewriting stored data:

- raw readings stay stored exactly as captured
- compatible unit ranges are grouped into cleaner replay views
- mode is only retained where it is meaningful for replay
- tiny transitional / unknown groups are suppressed from the filter UI
- `All Measurements` remains available as a mixed-session overview

### Workflows

The Workflows tab supports:

- selecting a built-in workflow
- starting a workflow run against the active session stack
- completing, continuing, retaking, skipping, or canceling steps
- per-step interaction modes:
  - `manual_check`
  - `stable_capture`
  - `countdown_capture`
  - `observe_and_confirm`
- capture steps that validate the current live reading type / unit
- staged capture confirmation for pause-after-capture steps
- recent workflow run history stored in SQLite
- selecting recent runs to review historical step results
- in-app workflow reports for the selected run
- Markdown export of workflow run reports

Built-in workflow pack:

- Battery Pack Check
- Solar Panel Test
- Charger Output Check
- Continuity Checklist

## Workflows

Workflow definitions are data-driven JSON files under `workflows/`.

Example shape:

```json
{
  "workflow_id": "battery_pack_check_v1",
  "title": "Battery Pack Check",
  "steps": [
    {
      "id": "measure_total_voltage",
      "instruction": "Measure total pack voltage.",
      "interaction_mode": "stable_capture",
      "advance_on_capture": false,
      "capture": true,
      "capture_settings": {
        "stable_for_s": 0.75,
        "min_samples": 5,
        "relative_tolerance": 0.01
      },
      "expected_measurement_type": "voltage_dc",
      "expected_unit": "V"
    }
  ]
}
```

Legacy workflow JSON that only uses `capture: true/false` still loads. New workflow definitions should prefer explicit `interaction_mode`, `advance_on_capture`, and `capture_settings`.

## Plugin Boundary

The project now includes a lightweight plugin loader in `packages/fluke_plugins/`.

Plugins can contribute:

- new `DeviceProfile` implementations
- additional workflow JSON directories
- fixture directories

Discovery root:

```text
plugins/
```

See:

- [plugins/README.md](plugins/README.md)
- [docs/developer/new-device-profile.md](docs/developer/new-device-profile.md)
- `plugins/examples/example_profile_plugin/`

Important note: the built-in `fluke_376fc` path still ships from the core codebase. Plugins are currently additive and intended for experimentation and contribution.

## Diagnostics And Contributor Tooling

### Raw fixture capture

- CLI: `fluke fixtures capture`
- script: `scripts/fixture_capture.py`

### Debug bundle export

- CLI: `fluke debug bundle`
- script: `scripts/export_debug_bundle.py`

These are meant to lower the barrier for remote debugging when hardware is unavailable.

## Data Model Summary

### Reading

- timestamp
- value
- unit
- measurement type
- status
- display text
- source device

### Session

- title
- notes
- tags
- device id
- start / end time
- profile id

### Marker

- session id
- timestamp
- label
- note

### Workflow Run

- workflow id
- session id
- start / end time
- run result

## Testing

Quick regression suite used during active development:

```bash
python -m unittest tests.unit.test_cli_main tests.unit.test_desktop_presenter tests.unit.test_desktop_views tests.unit.test_sdk_client
```

Full suite:

```bash
python -m unittest discover -s tests -p "test_*.py"
python -m compileall apps packages tests
```

The test strategy is intentionally layered:

- parser and statistics unit tests
- fake-adapter integration tests
- desktop presenter tests without hardware
- workflow runner tests
- plugin loader tests
- fixture capture and debug bundle tests

## Legacy Prototype

`fluke_ble.py` is still in the repo because it contains the original reverse-engineered implementation and remains useful reference material. It is not the long-term architectural center of the project anymore.

Prefer the shared stack unless you are specifically mining the legacy script for protocol details.

## Documentation Index

- [docs/README.md](docs/README.md)
- [docs/getting-started.md](docs/getting-started.md)
- [docs/desktop-guide.md](docs/desktop-guide.md)
- [docs/cli-guide.md](docs/cli-guide.md)
- [docs/data-and-exports.md](docs/data-and-exports.md)
- [docs/sdk-guide.md](docs/sdk-guide.md)
- [docs/workflows-page.md](docs/workflows-page.md)
- [docs/developer/README.md](docs/developer/README.md)
- [docs/developer/development-workflow.md](docs/developer/development-workflow.md)
- [docs/developer/testing-guide.md](docs/developer/testing-guide.md)
- [docs/developer/desktop-ui-architecture.md](docs/developer/desktop-ui-architecture.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/support-matrix.md](docs/support-matrix.md)
- [docs/developer/new-device-profile.md](docs/developer/new-device-profile.md)
- [docs/developer/fixtures-and-debug.md](docs/developer/fixtures-and-debug.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)

## Current Roadmap Direction

Already implemented:

- shared BLE + protocol + CLI slice
- session logging and exports
- desktop live / session UX
- charts, markers, summaries, and chart export
- guided workflows
- workflow run review and reporting
- plugin boundary, fixture capture, and debug bundle export

Next likely work:

- more real hardware validation
- additional profile support
- packaging and installer work
- contributor docs expansion
