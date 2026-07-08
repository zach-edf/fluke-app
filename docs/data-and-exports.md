# Data and Exports Guide

This guide explains what data the app stores, where it stores it, and what export files the desktop app and CLI can generate.

## Storage Model Overview

The project uses SQLite for persisted application data.

The shared data model includes:

- recent devices
- assets
- sessions (optionally linked to an asset)
- readings
- markers
- workflow runs (optionally linked to an asset)
- workflow step results

These records are used by both the desktop app and the CLI.

## Default Database Location

When no explicit database path is provided, the shared stack uses a platform-specific default:

- Windows: `%LOCALAPPDATA%/fluke-community/fluke.db`
- macOS: `~/Library/Application Support/fluke-community/fluke.db`
- Linux: `~/.local/share/fluke-community/fluke.db`

## Desktop Database Behavior

The desktop app currently uses the shared default database path.

Important notes:

- the current desktop `Settings` tab shows the database path
- the desktop UI does not currently expose a control to change the database location
- recent devices, sessions, markers, and workflow run history all come from the same shared database

## CLI Database Behavior

Several CLI commands allow an explicit `--database` path.

This is useful when you want:

- a temporary test database
- an isolated workflow database
- a non-default data location

Commands that commonly accept `--database`:

- `fluke log`
- `fluke sessions ...`
- `fluke assets ...`
- `fluke workflow run`
- `fluke debug bundle`

## What A Session Stores

A recorded session can include:

- session id
- device id
- title
- notes
- tags
- app version
- profile id
- optional asset id (when linked to a tracked asset)
- start time
- end time
- all readings recorded during the session
- all markers recorded during the session

## What An Asset Stores

A tracked asset records:

- asset id
- name
- asset type (free text, with suggested categories)
- location
- notes
- created-at timestamp

Assets and their linkage were added in SQLite schema version 4. Existing
databases upgrade automatically by adding a nullable `asset_id` column to
`sessions` and `workflow_runs`; sessions recorded before the upgrade remain
unassigned. See the [Assets and Trending Guide](assets-and-trending.md).

## What A Marker Stores

A session marker records:

- the target session id
- timestamp
- label
- note text

Markers can come from:

- manual user input in the desktop live view
- workflow step activity
- system events such as alert triggers or reconnect/disconnect events

## What A Workflow Run Stores

A workflow run records:

- workflow id
- workflow title
- session id
- start time
- end time
- run result
- overall pass/fail verdict
- report metadata (customer, site, job number, technician, business name, logo path, notes)

Each completed or skipped workflow step is stored as a workflow step result.

That result can include:

- step id
- step index
- completion time
- step status
- optional note
- optional captured reading
- pass/fail verdict and the limit-check detail text (for capture steps with acceptance criteria)

These verdict and report-metadata columns were added in schema version 4 and are
migrated onto existing databases automatically.

## Replay Filtering and Comparison

The session replay page can derive filtered replay views from mixed-mode sessions.

Important behavior:

- raw readings remain stored exactly as captured
- replay filters are derived for display only
- derived segments are computed from replay context changes and long reading gaps
- the session page can compare a selected replay view against another session if a matching replay context exists
- per-segment view is intended for single-session inspection rather than cross-session overlay

This means the UI improves replay clarity without mutating stored raw data.

## Desktop Exports

The desktop app can generate several export types.

### Raw CSV

Generated from the `Session` tab.

Typical desktop file name:

- `session-<SESSION_ID>.csv`

This is the canonical sequential event export.

### Raw JSON

Generated from the `Session` tab.

Typical desktop file name:

- `session-<SESSION_ID>.json`

This is the canonical structured session export with session metadata, readings, and markers.

### Analysis CSV

Generated from the `Session` tab.

Typical desktop file name:

- `session-<SESSION_ID>-analysis.csv`

Shape:

- one `timestamp_utc` column
- one column per normalized measurement view
- sparse rows are allowed
- no resampling is performed

### Segment Summary JSON

Generated from the `Session` tab.

Typical desktop file name:

- `session-<SESSION_ID>-segments.json`

This export includes session metadata, derived segments, per-segment statistics, and marker summaries grouped by segment.

### Session Chart PNG

Generated from the `Session` tab.

Typical desktop file name:

- `session-<SESSION_ID>-chart.png`

### Live Chart PNG

Generated from the `Live Reading` tab.

Typical desktop file name:

- `live-chart.png`

### Asset Trend CSV

Generated from the `Assets` tab (**Export Trend CSV**).

Typical desktop file name:

- `asset-<ASSET_ID>-trend.csv`

Shape:

- one row per session per measurement group
- columns: `asset_id`, `measurement`, `label`, `unit`, `session_id`,
  `session_title`, `started_at`, `reading_count`, `numeric_count`, `min`, `max`,
  `avg`, `median`
- mixed-unit sessions are normalized to a single display unit per measurement

### Asset Trend Chart PNG

Generated from the `Assets` tab (**Export Trend Chart**).

Typical desktop file name:

- `asset-<ASSET_ID>-trend.png`

### Workflow Report Markdown

Generated from the `Workflows` tab.

Typical desktop file name:

- `workflow-run-<RUN_ID>.md`

### Workflow PDF Job Report

Generated from the `Workflows` tab with the `Export PDF Report` button (enabled
when a run is selected). The PDF is a professional job report containing an
optional business name/logo, customer/site/job/technician fields, device model
and serial, a per-step table (reading, limits, PASS/FAIL, notes), the overall
verdict, and a small chart of comparable captured values.

Typical desktop file name:

- `workflow-run-<RUN_ID>.pdf`

PDF rendering uses the optional `reportlab` dependency (`.[reports]` or
`.[full]` extra). The shared implementation lives in
`packages/fluke_app/report_service.py` and is reused by the CLI.

## Desktop Export Directory Behavior

The desktop app builds export paths from the export directory shown in the `Settings` tab.

Important notes:

- the default export directory is `exports`
- the `Apply Export Directory` control updates the export location for the current app run
- the export directory setting is not currently persisted across app restarts

## CLI Exports

The CLI supports explicit export paths.

### Session export through `log`

`fluke log` can export the just-recorded session immediately after capture:

- `--csv-output`
- `--json-output`

### Session export through `sessions export`

Use:

- `--format csv`
- `--format json`
- `--output`

The CLI currently exposes the raw export formats only. The analysis CSV and segment summary JSON exports are desktop-only in this phase.

### Asset trend export through `assets trend`

Use `fluke assets trend --asset <ASSET_ID> --csv-output <PATH>` to write the asset
trend CSV (one row per session per measurement group with min/max/avg/median).

### Workflow output

The CLI workflow runner stores workflow runs in the database, including pass/fail
verdicts. Review runs with `fluke workflow history` (add `--run <RUN_ID>` for
per-step verdict detail).

### Workflow PDF report through `workflow report`

Render a stored run to a PDF job report:

```powershell
fluke workflow report --run "<RUN_ID>" --output report.pdf --customer "Jane Doe" --job "JOB-42"
```

The `--customer`, `--site`, `--job`, `--technician`, `--business-name`, `--logo`,
and `--report-notes` flags are persisted with the run so future reports reuse
them. Requires the `reportlab` package (`.[reports]` / `.[full]` extra).

### Diagnostics exports

The CLI can also create:

- raw fixture JSON files through `fluke fixtures capture`
- debug bundle zip files through `fluke debug bundle`

## Debug Bundle Contents

The debug bundle is intended for bug reports and contributor triage.

It summarizes:

- supported profiles
- workflow inventory
- plugin inventory
- database contents and metadata

Use it when you need a single artifact that captures the current runtime and data state.

## Raw Fixture Files

Fixture capture is meant for low-level diagnostics and protocol work.

A fixture JSON file stores captured raw BLE frames for a device/profile combination and can be used later for replay, debugging, or contributor validation.

## Workflow Definition Files

Workflow definitions are stored as JSON files under:

- [workflows](../workflows)

These files are separate from runtime workflow run data.

Difference:

- workflow definition files describe what a workflow is
- workflow run records describe how a specific execution of that workflow went

Notes:

- legacy files that only use `capture: true/false` still load
- new files should prefer explicit `interaction_mode`, `advance_on_capture`, and `capture_settings`

For workflow authoring details, see [Workflows Page Guide](workflows-page.md).

## Export Troubleshooting

### Export completed but I cannot find the file

Check:

- the export directory in the desktop `Settings` tab
- the explicit `--output` path passed on the CLI
- whether you are looking for a chart PNG, raw export, analysis export, segment summary export, or workflow report

### Session export fails

Check:

- that the session id exists
- that the selected session is actually loaded in the desktop UI
- that the output directory is writable

### Workflow report export fails

Check:

- that a workflow run is selected
- that a workflow run actually exists for the current selection
- that the output directory is writable

### Analysis or segment export looks different from the raw export

That is expected.

- raw CSV and raw JSON preserve the sequential event stream
- analysis CSV reshapes readings into a sparse wide table
- segment summary JSON groups derived segments and marker summaries for review

### A workflow exists but no run history appears

Remember:

- workflow definitions live in JSON files
- workflow run history only appears after the workflow has been executed

## Related Guides

- [Getting Started](getting-started.md)
- [Desktop User Guide](desktop-guide.md)
- [CLI Guide](cli-guide.md)
- [Workflows Page Guide](workflows-page.md)
- [Assets and Trending Guide](assets-and-trending.md)
