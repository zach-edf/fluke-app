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
- `--speak` and speech options (see [Spoken readings](#spoken-readings-tts))
- `--mqtt-host` and MQTT options (see [MQTT publishing](#mqtt-publishing))

Examples:

```powershell
fluke stream --device "<DEVICE_ID>" --count 25
fluke stream --device "<DEVICE_ID>" --duration 30
fluke stream --device "<DEVICE_ID>" --dashboard
fluke stream --device "<DEVICE_ID>" --no-reconnect
fluke stream --device "<DEVICE_ID>" --speak --speak-interval 15
fluke stream --device "<DEVICE_ID>" --mqtt-host 192.168.1.10 --mqtt-topic fluke
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

Alarm logic is provided by the shared `AlertEvaluator` service, so the CLI and
desktop app behave identically. Alarms fire on high/low value crossings, on an
out-of-band duration (debounce), and on reading-status conditions (over-range,
no-signal). A connection drop is also reported.

Options:

- `--device`
- `--profile`
- `--high`
- `--low`
- `--debounce` — require the value to stay out of band for N seconds before alerting
- `--no-status-alerts` — do not alert on over-range / no-signal status
- `--duration`
- `--bell`
- `--no-bell`
- `--speak` and speech options (see [Spoken readings](#spoken-readings-tts)) — spoken alerts are announced on trigger

Examples:

```powershell
fluke alert --device "<DEVICE_ID>" --high 120
fluke alert --device "<DEVICE_ID>" --low 10 --high 120 --duration 60
fluke alert --device "<DEVICE_ID>" --high 120 --debounce 2
fluke alert --device "<DEVICE_ID>" --high 120 --no-bell
fluke alert --device "<DEVICE_ID>" --high 120 --speak
```

With no thresholds and status alerts still enabled, the command alerts only on
meter status conditions. If both thresholds and status alerts are disabled, the
command warns that no alerts are active.

### Spoken readings (TTS)

`fluke stream` and `fluke alert` accept `--speak` to announce readings aloud
using a platform-native engine (Windows SAPI, macOS `say`, Linux `espeak`, or
`pyttsx3`). If no engine is available the flag is a no-op and a warning is
printed. Readings are pronounced with unit expansion, e.g. `121.3 V` AC becomes
"one hundred twenty-one point three volts A C".

Options (shared by both commands):

- `--speak` — enable spoken readings
- `--speak-mode {interval,on_stable,on_change,on_alert}` — when to speak (default `interval`)
- `--speak-interval N` — seconds between spoken readings in interval mode
- `--speak-delta N` — minimum change to announce in `on_change` mode

In `fluke alert`, alert transitions are always spoken regardless of mode.

### MQTT publishing

`fluke stream` and `fluke log` can publish each reading to an MQTT broker when
`--mqtt-host` is provided. See [docs/integrations.md](integrations.md) for the
full topic layout and Home Assistant setup.

Options (shared by both commands):

- `--mqtt-host` — broker host (enables publishing)
- `--mqtt-port` — broker port (default 1883)
- `--mqtt-username` / `--mqtt-password`
- `--mqtt-tls`
- `--mqtt-topic` — base topic (default `fluke`)
- `--mqtt-qos {0,1,2}`
- `--mqtt-retain`
- `--mqtt-no-discovery` — disable Home Assistant MQTT discovery

MQTT support requires the optional extra: `pip install -e ".[mqtt]"`.

### `serve`

Use this to serve a LAN-only live web view so a helper can watch the live
reading from a phone browser on the same network. It connects, streams, and
serves; on startup it prints the reachable URLs and a scannable terminal QR
code.

```powershell
fluke serve --device "<DEVICE_ID>" --profile fluke_376fc
```

Options:

- `--device`
- `--profile`
- `--port` (default `8765`)
- `--host` (default `0.0.0.0`)
- `--token` (optional shared-secret query-param gate)
- `--stale-after` (seconds before data is flagged stale, default `3.0`)
- `--read-only` (default; the web view never controls the meter)
- `--duration`
- `--no-qr`
- `--log` and the log-related options (`--database`, `--title`, `--notes`,
  `--tags`, `--csv-output`, `--json-output`)

Examples:

```powershell
fluke serve --device "<DEVICE_ID>" --port 9000 --token s3cret
fluke serve --device "<DEVICE_ID>" --host 127.0.0.1
fluke serve --device "<DEVICE_ID>" --log --title "Panel check" --csv-output exports/panel.csv
```

Endpoints: `/` (page), `/ws` (WebSocket feed), `/api/status`, `/api/latest`.

This is a trusted-LAN tool: it binds to all interfaces by default, has no
authentication in v1 beyond the optional `--token` gate, uses plain HTTP, and is
read-only by construction. See [LAN Live Web View](web-live-view.md) for the
full guide and security notes.

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
- `--asset` (attach the session to a tracked asset id; the asset must already exist)
- `--csv-output`
- `--json-output`
- `--quiet`
- `--no-reconnect`
- `--mqtt-host` and MQTT options (see [MQTT publishing](#mqtt-publishing))

Examples:

```powershell
fluke log --device "<DEVICE_ID>" --count 100
fluke log --device "<DEVICE_ID>" --duration 60 --tags "battery,validation"
fluke log --device "<DEVICE_ID>" --duration 30 --csv-output exports/session.csv --json-output exports/session.json
fluke log --device "<DEVICE_ID>" --duration 60 --mqtt-host 192.168.1.10
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
- `--asset` on `list` (only show sessions linked to that asset id)

Example:

```powershell
fluke sessions --database C:\path\to\fluke.db list --limit 10
fluke sessions list --asset <ASSET_ID>
```

### `sessions assign-asset`

Use this to link or unlink a recorded session to a tracked asset.

```powershell
fluke sessions assign-asset --session "<SESSION_ID>" --asset <ASSET_ID>
```

Options:

- `--database` on the parent `sessions` command
- `--session`
- `--asset` (omit to clear the session's asset link)

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

### `assets`

Use these to manage tracked equipment and trend its readings over time. See the
[Assets and Trending Guide](assets-and-trending.md) for the full feature tour.

`--database` is a group-level flag on the `assets` command, so it goes before the
subcommand.

```powershell
fluke assets create --name "Line 3 Motor" --type motor --location "Bay 2"
fluke assets list
fluke assets show --asset <ASSET_ID>
fluke assets trend --asset <ASSET_ID>
```

Subcommands and options:

- `assets create`: `--name` (required), `--type`, `--location`, `--notes`, `--id`
- `assets list`: `--limit`
- `assets show`: `--asset` (required)
- `assets trend`: `--asset` (required), `--measurement`, `--csv-output`

`list`, `show`, and `trend` all support the global `--json` flag. `assets trend`
prints a per-session table of min/max/avg/median statistics for each measurement
type, normalizing mixed-unit sessions to a common display unit.

```powershell
fluke --json assets trend --asset <ASSET_ID> --measurement current_inrush
fluke assets trend --asset <ASSET_ID> --csv-output exports/asset-trend.csv
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
- for capture steps with acceptance criteria, prints a `PASS` / `FAIL` verdict
  with the limit that failed, and prints an overall run verdict at the end

### `workflow history`

Use this to review recent workflow runs and their verdicts.

```powershell
fluke workflow history
fluke workflow history --run "<RUN_ID>"
fluke --json workflow history
```

Options:

- `--limit` (number of recent runs; default 10)
- `--run` (show per-step status, readings, and PASS/FAIL detail for one run)
- `--database`

### `workflow report`

Use this to render a completed workflow run into a professional PDF job report.

```powershell
fluke workflow report --run "<RUN_ID>" --output report.pdf --customer "Jane Doe" --job "JOB-42" --technician "Zach V"
```

Options:

- `--run` (required) and `--output` (required)
- `--business-name`, `--logo`
- `--customer`, `--site`, `--job`, `--technician`, `--report-notes`
- `--database`

The customer/site/job/technician/business metadata is persisted with the run so
later reports reuse it. PDF rendering requires the `reportlab` package (install
the `.[reports]` or `.[full]` extra).

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
- `sessions assign-asset`
- `sessions import-device-memory`
- `sessions export`
- `assets` (list, create, show, trend)
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
- [Assets and Trending Guide](assets-and-trending.md)
- [Data and Exports Guide](data-and-exports.md)
- [SDK Guide](sdk-guide.md)
- [LAN Live Web View](web-live-view.md)
