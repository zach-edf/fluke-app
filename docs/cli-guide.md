# CLI Guide

This guide documents the `fluke` command-line interface.

## Overview

The CLI is the fastest way to:

- scan for devices
- stream live readings
- record sessions into SQLite
- import saved device-memory sessions into SQLite
- export session data
- run workflows from the terminal
- inspect plugins and supported profiles
- capture diagnostics artifacts

## Entry Points

Installed entry points:

- `fluke`
- `fluke-cli`

Module fallback:

```powershell
python -m apps.cli.main --help
```

## Global Options

The root command supports:

- `--version`
- `-v` or `--verbose`
- `--json`

### `--json`

`--json` is a global flag, so place it before the command:

```powershell
fluke --json scan --timeout 5
```

It is most useful on commands that emit lists or structured summaries.

Examples:

- `fluke --json scan --timeout 5`
- `fluke --json devices supported`
- `fluke --json sessions list`
- `fluke --json workflow list`
- `fluke --json plugins list`

Not every command emits rich JSON. Some commands still print plain output or a single path string.

## Device IDs and Profile IDs

Many commands require:

- a BLE device identifier from scan output
- a device profile id

For the current built-in path, the default profile is typically:

- `fluke_376fc`

If you are using plugin-contributed profiles, use:

```powershell
fluke devices supported
```

to see the loaded registry.

## Command Reference

### `scan`

Use this to discover nearby BLE devices.

```powershell
fluke scan --timeout 10
```

Options:

- `--timeout`: scan duration in seconds
- `--name`: optional name filter

Example:

```powershell
fluke scan --timeout 10 --name Fluke
```

### `stream`

Use this to connect and print normalized live readings.

```powershell
fluke stream --device "<DEVICE_ID>" --profile fluke_376fc
```

Options:

- `--device`
- `--profile`
- `--duration`
- `--count`
- `--dashboard`
- `--no-reconnect`

Examples:

```powershell
fluke stream --device "<DEVICE_ID>" --count 25
fluke stream --device "<DEVICE_ID>" --duration 30
fluke stream --device "<DEVICE_ID>" --dashboard
fluke stream --device "<DEVICE_ID>" --no-reconnect
```

Use `--dashboard` if you want the retro terminal dashboard instead of plain line output.

### `watch`

Use this when you want a compact single-line live monitor instead of full stream output.

```powershell
fluke watch --device "<DEVICE_ID>" --profile fluke_376fc
```

Options:

- `--device`
- `--profile`
- `--duration`
- `--no-reconnect`

This mode updates a single terminal line with:

- current reading
- measurement type
- reading status
- sample count

### `alert`

Use this to stream readings and trigger threshold alerts.

```powershell
fluke alert --device "<DEVICE_ID>" --high 120
```

Options:

- `--device`
- `--profile`
- `--high`
- `--low`
- `--duration`
- `--bell`
- `--no-bell`

Examples:

```powershell
fluke alert --device "<DEVICE_ID>" --high 120
fluke alert --device "<DEVICE_ID>" --low 10 --high 120 --duration 60
fluke alert --device "<DEVICE_ID>" --high 120 --no-bell
```

If neither threshold is supplied, the command still runs but warns that no alert thresholds are active.

### `log`

Use this to record readings to SQLite and optionally export the session immediately.

```powershell
fluke log `
  --device "<DEVICE_ID>" `
  --profile fluke_376fc `
  --duration 30 `
  --title "Bench run"
```

Options:

- `--device`
- `--profile`
- `--database`
- `--duration`
- `--count`
- `--title`
- `--notes`
- `--tags`
- `--csv-output`
- `--json-output`
- `--quiet`
- `--no-reconnect`

Examples:

```powershell
fluke log --device "<DEVICE_ID>" --count 100
fluke log --device "<DEVICE_ID>" --duration 60 --tags "battery,validation"
fluke log --device "<DEVICE_ID>" --duration 30 --csv-output exports/session.csv --json-output exports/session.json
```

Behavior:

- readings are recorded into SQLite as they arrive
- the command stops on `Ctrl+C`, duration, or count limit
- if export paths are provided, exports happen after the session is completed

Automatic reconnect (all of `stream`, `watch`, and `log`):

- an unexpected BLE drop triggers automatic reconnect with exponential backoff
  and jitter; status lines are printed to stderr (for example
  `[recovery:direct connect (1/2)] ...`)
- for `log`, the recording session is kept open across the drop; readings keep
  appending to the same session id and `connection_lost` / `connection_restored`
  markers bracket the gap in the stored session
- pass `--no-reconnect` to disable this; the first unexpected drop then ends the
  command (and, for `log`, finalizes the session)
- a `Ctrl+C` / user-initiated stop is never treated as an unexpected drop

### `sessions list`

Use this to inspect recent recorded sessions.

```powershell
fluke sessions list
```

Options:

- `--database` on the parent `sessions` command
- `--limit` on `list`

Example:

```powershell
fluke sessions --database C:\path\to\fluke.db list --limit 10
```

### `sessions export`

Use this to export a previously recorded session.

```powershell
fluke sessions export --session "<SESSION_ID>" --format json --output exports/session.json
```

Options:

- `--database` on the parent `sessions` command
- `--session`
- `--format {csv,json}`
- `--output`

Examples:

```powershell
fluke sessions export --session "<SESSION_ID>" --format csv --output exports/session.csv
fluke sessions export --session "<SESSION_ID>" --format json --output exports/session.json
```

### `sessions import-device-memory`

Use this to download saved on-device logging sessions and persist them as normal sessions/readings in the local database.

```powershell
fluke sessions import-device-memory `
  --device "<DEVICE_ID>" `
  --value-source average `
  --data-output artifacts/device-memory.bin `
  --download-report-output artifacts/device-memory.json
```

Behavior:

- runs the validated Fluke 376 FC device-memory download flow
- decodes recognized 18-byte blocks into sessions and detail rows
- imports each decoded saved session as a normal SQLite session with readings
- defaults to importing the `average` value from each detail block
- skips sessions that were already imported earlier from the same raw payload

Options:

- `--database` on the parent `sessions` command
- `--device`
- `--value-source {average,maximum,minimum}`
- `--data-output`
- `--download-report-output`
- `--max-blocks-per-request`
- `--command-timeout-seconds`

### `workflow list`

Use this to see the workflow catalog currently available to the CLI.

```powershell
fluke workflow list
```

This includes:

- built-in workflows
- plugin-contributed workflows

### `workflow run`

Use this to run a guided workflow interactively in the terminal.

```powershell
fluke workflow run --workflow battery_pack_check_v1 --device "<DEVICE_ID>"
```

Options:

- `--workflow`
- `--device`
- `--profile`
- `--database`
- `--timeout`

Behavior:

- the CLI connects to the device
- creates a session automatically
- starts the workflow run
- prints each step
- waits for input
- for capture steps, uses the latest live reading when you confirm capture
- `Enter` completes or captures the step
- `s` skips the step

For deeper workflow semantics and the desktop workflow page, see [Workflows Page Guide](workflows-page.md).

### `devices supported`

Use this to list the currently loaded profile registry.

```powershell
fluke devices supported
```

This is useful when you need to confirm:

- built-in support
- plugin-contributed profiles
- exact profile ids to pass to other commands

### `plugins list`

Use this to inspect discovered plugins.

```powershell
fluke plugins list
```

The output shows which plugins are loaded and what they contribute.

### `fixtures capture`

Use this to capture raw BLE notification fixtures for diagnostics or contributor workflows.

```powershell
fluke fixtures capture `
  --device "<DEVICE_ID>" `
  --profile fluke_376fc `
  --duration 10 `
  --output fixtures/capture.json
```

Options:

- `--device`
- `--profile`
- `--duration`
- `--count`
- `--output`

This command is primarily aimed at diagnostics and contribution work rather than routine end-user operation.

### `debug bundle`

Use this to export a diagnostic zip bundle for bug reports and contributor triage.

```powershell
fluke debug bundle --output artifacts/debug-bundle.zip
```

Options:

- `--output`
- `--database`

The debug bundle includes summarized information about:

- supported profiles
- workflows
- plugins
- database state

### `debug probe`

Use this to inspect a connected device's GATT layout and capture evidence for unsupported BLE features.

```powershell
fluke debug probe --device "<DEVICE_ID>" --read --notify-seconds 5 --output artifacts/probe.json
```

Options:

- `--device`
- `--read`
- `--notify-seconds`
- `--output`

Behavior:

- connects directly to the target BLE device
- enumerates services and characteristics
- optionally attempts reads on readable characteristics
- optionally subscribes to notify and indicate characteristics for a short capture window
- prints a summary and can save the full JSON report for later analysis

### `debug transact`

Use this to inspect a single characteristic with controlled read, write, and notify capture steps.

```powershell
fluke debug transact --device "<DEVICE_ID>" --char <UUID> --read-before --write-hex "01" --read-after
```

Options:

- `--device`
- `--char`
- `--read-before`
- `--write-hex`
- `--write-mode {auto,response,no-response}`
- `--read-after`
- `--notify-seconds`
- `--settle-seconds`
- `--output`

### `debug logging-config`

Use this to read and decode the Fluke 376 FC logging settings characteristic.

```powershell
fluke debug logging-config --device "<DEVICE_ID>" --output artifacts/logging-config.json
```

Behavior:

- reads characteristic `b6982907-7562-11e2-b50d-00163e46f8fe`
- decodes the payload as:
  - bytes `0-3`: interval in seconds, little-endian `uint32`
  - bytes `4-7`: duration in seconds, little-endian `uint32`
- reports `duration_seconds = 0` as the app's `Manual` duration mode

### `debug logging-config-set`

Use this to write an experimental logging interval and duration to the meter.

```powershell
fluke debug logging-config-set `
  --device "<DEVICE_ID>" `
  --interval-seconds 165 `
  --duration-seconds 7200 `
  --read-before `
  --read-after
```

Behavior:

- writes the validated 8-byte config layout
- does not require a separate apply step for the validated finite-duration case

### `debug logging-download`

Use this to run the validated saved-memory download flow on the Fluke 376 FC.

```powershell
fluke debug logging-download `
  --device "<DEVICE_ID>" `
  --data-output artifacts/logging-download.bin `
  --output artifacts/logging-download.json
```

Behavior:

- reads `2906` status and `290d` capacity
- subscribes to:
  - `2906` status notifications
  - `2908` control-point notifications
  - `2917` download-buffer notifications
- if needed, writes `0x83` to `2908` to lock for download
- requests blocks from `2917` using the 9-byte `0x84 + start_block + block_count` control-point payload
- saves the raw downloaded bytes and a JSON report with control/status transitions
- decodes any recognized 18-byte logging blocks into session/header/detail summaries under `decoded_sessions`
- unlocks with `0x86` when finished

## Common CLI Workflows

### Discover and stream

```powershell
fluke scan --timeout 10
fluke stream --device "<DEVICE_ID>" --profile fluke_376fc
```

### Capture a short session and export it

```powershell
fluke log `
  --device "<DEVICE_ID>" `
  --profile fluke_376fc `
  --duration 20 `
  --title "Quick capture" `
  --csv-output exports/quick.csv `
  --json-output exports/quick.json
```

### Review recent sessions

```powershell
fluke sessions list
fluke sessions export --session "<SESSION_ID>" --format json --output exports/session.json
fluke sessions import-device-memory --device "<DEVICE_ID>"
```

### Run a workflow

```powershell
fluke workflow list
fluke workflow run --workflow battery_pack_check_v1 --device "<DEVICE_ID>"
```

### Capture diagnostics artifacts

```powershell
fluke fixtures capture --device "<DEVICE_ID>" --profile fluke_376fc --duration 10 --output fixtures/capture.json
fluke debug probe --device "<DEVICE_ID>" --read --notify-seconds 5 --output artifacts/probe.json
fluke debug bundle --output artifacts/debug-bundle.zip
```

## Database Path Behavior

Several CLI commands accept `--database`.

If `--database` is omitted, the CLI uses the shared platform-specific default path:

- Windows: `%LOCALAPPDATA%/fluke-community/fluke.db`
- macOS: `~/Library/Application Support/fluke-community/fluke.db`
- Linux: `~/.local/share/fluke-community/fluke.db`

Commands that commonly use the database:

- `log`
- `sessions list`
- `sessions import-device-memory`
- `sessions export`
- `workflow run`
- `debug bundle`

## Tips

- use `scan` first and copy the exact device id into later commands
- use `--count` when you want a deterministic sample size
- use `--duration` when you want a fixed capture window
- use `--quiet` with `log` if you care only about the stored session and not terminal output
- use `--json` when scripting list output

## Related Guides

- [Getting Started](getting-started.md)
- [Desktop User Guide](desktop-guide.md)
- [Workflows Page Guide](workflows-page.md)
- [Data and Exports Guide](data-and-exports.md)
- [SDK Guide](sdk-guide.md)
