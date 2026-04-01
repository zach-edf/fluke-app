# CLI Guide

This guide documents the `fluke` command-line interface.

## Overview

The CLI is the fastest way to:

- scan for devices
- stream live readings
- record sessions into SQLite
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

Examples:

```powershell
fluke stream --device "<DEVICE_ID>" --count 25
fluke stream --device "<DEVICE_ID>" --duration 30
fluke stream --device "<DEVICE_ID>" --dashboard
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
```

### Run a workflow

```powershell
fluke workflow list
fluke workflow run --workflow battery_pack_check_v1 --device "<DEVICE_ID>"
```

### Capture diagnostics artifacts

```powershell
fluke fixtures capture --device "<DEVICE_ID>" --profile fluke_376fc --duration 10 --output fixtures/capture.json
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
