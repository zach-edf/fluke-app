# Fixtures And Debug Bundles

These tools exist so contributors can move work forward without direct hardware access.

## Raw Fixture Capture

Use the CLI:

```powershell
.\.venv\Scripts\python.exe -m apps.cli.main fixtures capture `
  --device "<DEVICE_ID>" `
  --profile fluke_376fc `
  --duration 10 `
  --output fixtures/fluke_376fc_capture.json
```

Or use the standalone script:

```powershell
.\.venv\Scripts\python.exe scripts\fixture_capture.py `
  --device "<DEVICE_ID>" `
  --profile fluke_376fc `
  --duration 10 `
  --output fixtures\capture.json
```

The resulting JSON records:

- device id
- profile id
- capture start/end times
- raw notification frames as hex payloads

## Debug Bundle Export

Use the CLI:

```powershell
.\.venv\Scripts\python.exe -m apps.cli.main debug bundle `
  --database data\fluke.db `
  --output artifacts\debug-bundle.zip
```

Or use the standalone script:

```powershell
.\.venv\Scripts\python.exe scripts\export_debug_bundle.py `
  --database data\fluke.db `
  --output artifacts\debug-bundle.zip
```

The bundle includes:

- environment manifest
- profile inventory
- workflow inventory
- loaded plugin metadata
- optional database snapshot summary if the SQLite file exists

## BLE Probe

Use the CLI:

```powershell
.\.venv\Scripts\python.exe -m apps.cli.main debug probe `
  --device "<DEVICE_ID>" `
  --read `
  --notify-seconds 5 `
  --output artifacts\probe.json
```

The probe report includes:

- service UUIDs and descriptions
- characteristic UUIDs and properties
- optional read payloads as hex
- optional notification samples captured during the probe window

## When To Use Which

- capture raw fixture data when the problem is parser or profile related
- probe BLE services when you need to discover unsupported GATT endpoints or on-device transfer hooks
- export a debug bundle when the problem spans discovery, sessions, workflows, or contributor triage
