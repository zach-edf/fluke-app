# Fluke 376 FC Python Telemetry Toolkit

Turn your Fluke 376 FC into a scriptable measurement workflow:
- live terminal dashboard with an old-school instrument vibe,
- structured event engine and annotations,
- profile-based runs,
- CSV + SQLite + Parquet sinks,
- report exports (HTML/PDF/PNG),
- mode/function auditing against 376 FC capabilities.

This project is built for practical field/lab use: battery cells, tool packs, quick diagnostics, and repeatable test sessions.

## What This Gives You

- Fast BLE scanning and device inspection
- High-frequency capture of Fluke live characteristics
- Decoded values, modes, units, and inferred measurement functions
- Event markers for:
  - contact on/off
  - over-voltage
  - unstable readings
  - manual operator annotations (hotkeys)
- Session persistence and comparison in SQLite
- Parquet exports for analytics pipelines
- Publishable report artifacts from each run

## Platform Notes

- macOS: supported (your current setup)
- Windows: supported (same Python CLI; hotkeys use Windows keyboard APIs)
- Linux: should work for core BLE flow where BLE stack is available

## Install

Base install:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Optional packs:

```bash
pip install -r requirements-plot.txt
pip install -r requirements-dashboard.txt
pip install -r requirements-data.txt
```

Install everything:

```bash
pip install -r requirements-full.txt
```

## 60-Second Quickstart

1. Scan for your meter:

```bash
python fluke_ble.py scan --timeout 15 --name "Zach's 376FC"
```

2. Inspect services:

```bash
python fluke_ble.py inspect --device "<DEVICE_ID>"
```

3. Record the two known live Fluke characteristics:

```bash
python fluke_ble.py record \
  --device "<DEVICE_ID>" \
  --duration 120 \
  --chars "b6982901-7562-11e2-b50d-00163e46f8fe,b698290f-7562-11e2-b50d-00163e46f8fe" \
  --console changes \
  --out logs/session.csv
```

4. Clean/export transition readings:

```bash
python fluke_ble.py analyze --input logs/session.csv --out logs/session_clean.csv
```

## Command Map

- `scan`: find nearby BLE devices
- `inspect`: inspect GATT services/characteristics
- `record`: run a full telemetry session (dashboard, plot, sinks, events, reports)
- `analyze`: flatten raw capture into clean value transitions
- `modes`: audit mode/unit/function coverage from capture data
- `report`: generate report artifacts from existing captures
- `profile`: list/show/run preset workflows from `profiles/*.toml`
- `db`: inspect and compare sessions stored in SQLite

## Signature Workflows

### 1) Live Dashboard Session (cockpit mode)

```bash
python fluke_ble.py record \
  --device "<DEVICE_ID>" \
  --duration 180 \
  --console none \
  --dashboard \
  --dashboard-refresh-hz 6 \
  --chars "b6982901-7562-11e2-b50d-00163e46f8fe,b698290f-7562-11e2-b50d-00163e46f8fe" \
  --out logs/dashboard_session.csv
```

Use this when you want a single-screen operations view with live value, mode badge, sparkline, min/max, connection state, and event feed.

### 2) Battery Cell / Pack Session with Sinks + Report

```bash
python fluke_ble.py record \
  --device "<DEVICE_ID>" \
  --duration 180 \
  --dashboard \
  --plot \
  --plot-theme brand \
  --plot-save-png reports/live_brand.png \
  --sqlite logs/fluke_sessions.db \
  --parquet logs/parquet/battery_run.parquet \
  --report-dir reports \
  --report-formats html,pdf \
  --report-title "Battery Pack Validation Run" \
  --out logs/battery_run.csv
```

This produces a full archive for later analysis/comparison.

### 3) Profile-Driven Runs (recommended for repeatability)

Starter profiles included:
- `profiles/dc_battery_test.toml`
- `profiles/ac_line_check.toml`
- `profiles/mode_sweep.toml`

List profiles:

```bash
python fluke_ble.py profile --dir profiles list
```

Run a profile:

```bash
python fluke_ble.py profile --dir profiles run \
  --name dc_battery_test \
  --device "<DEVICE_ID>"
```

Override profile defaults on the fly:

```bash
python fluke_ble.py profile --dir profiles run \
  --name dc_battery_test \
  --device "<DEVICE_ID>" \
  --duration 300 \
  --plot-theme publication
```

### 4) Mode Coverage Validation (376 FC readiness)

Run sweep profile:

```bash
python fluke_ble.py profile --dir profiles run \
  --name mode_sweep \
  --device "<DEVICE_ID>"
```

Audit coverage:

```bash
python fluke_ble.py modes --input logs/mode_sweep.csv
```

`modes` reports:
- observed mode tokens and units,
- inferred function families,
- unknown-mode/unit findings,
- expected 376 FC function coverage (manual-driven checklist).

## Event Engine and Annotations

Rule controls:
- `--contact-threshold`
- `--over-voltage`
- `--unstable-delta`
- `--unstable-window`
- `--unstable-min-points`

Event output:
- default `*_events.csv` next to session CSV
- mirrored to SQLite/Parquet sinks when enabled
- shown in dashboard event feed

Annotation hotkeys:
- defaults: `b`, `o`, `m`, `n`
- custom map via `--annotation-map "b:Battery on,o:Battery off,..."`
- disable via `--no-hotkeys`
- interactive TTY only

## Data Sinks and Comparison

Enable SQLite + Parquet during record:

```bash
python fluke_ble.py record \
  --device "<DEVICE_ID>" \
  --sqlite logs/fluke_sessions.db \
  --parquet logs/parquet/session.parquet \
  --out logs/session.csv
```

Query sessions:

```bash
python fluke_ble.py db sessions --sqlite logs/fluke_sessions.db --limit 20
```

Compare sessions:

```bash
python fluke_ble.py db compare \
  --sqlite logs/fluke_sessions.db \
  --session-a <SESSION_ID_A> \
  --session-b <SESSION_ID_B>
```

## Reporting

Generate report from an existing capture:

```bash
python fluke_ble.py report \
  --input logs/session.csv \
  --events logs/session_events.csv \
  --out-dir reports \
  --theme publication \
  --formats html,pdf
```

Artifacts:
- `<stem>_chart.png`
- `<stem>_report.html`
- `<stem>_report.pdf`

## Output Schema (Capture CSV)

Primary fields in session CSV:
- `session_id`
- `timestamp_utc`
- `epoch_s`
- `characteristic_uuid`
- `source` (`read` or `notify`)
- `decoded_primary`
- `decoded_value`
- `decoded_unit`
- `decoded_mode`
- `decoded_mode_label`
- `decoded_mode_known`
- `decoded_unit_norm`
- `decoded_unit_known`
- `decoded_function`
- `decoded_status_tenths`

## Battery/Pack Test Ideas You Can Run Today

- Incoming QC: quick open-circuit + stability snapshot and auto report
- Load-step sag: annotate load on/off and inspect droop/recovery in timeline
- Intermittent fault hunt: flex connectors and monitor unstable-event density
- Pack benchmark: run same profile across packs and compare in SQLite
- Aging trend: repeat profile monthly, compare drift and event rates
- Inrush behavior: confirm startup transients for motorized tool loads

## Troubleshooting

- No BLE device found:
  - meter must be in Fluke Connect/BLE mode
  - keep Fluke Connect app disconnected while using this script
  - increase `--timeout`
- Bluetooth unavailable error:
  - ensure terminal app has Bluetooth permission in OS settings
- Dashboard or plot fails:
  - install optional deps (`requirements-dashboard.txt`, `requirements-plot.txt`)
- Parquet fails:
  - install `requirements-data.txt`
- Too many unknown modes/functions:
  - run `mode_sweep` profile and audit with `modes`
  - share output and extend mode/unit mappings

## Safety

This toolkit improves capture and analysis, but it does not replace safe measurement practice.
Follow Fluke operating limits, category ratings, and PPE requirements for live electrical work.

## Relevant Files

- Main CLI: `fluke_ble.py`
- Profiles: `profiles/*.toml`
- Reports: `reports/`
- Logs: `logs/`
- Manual reference: `376FC Manual.pdf`
