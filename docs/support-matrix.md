# Support Matrix

This matrix is intentionally conservative. A model should only move to `Supported` after the parser, session flow, and at least one hardware validation pass are all in place.

## Status Levels

- `Supported`: profile exists, shared stack integration exists, and real hardware validation has been performed
- `Experimental`: profile exists or is in progress, but hardware coverage is incomplete or assumptions remain
- `Unknown`: no profile or validation yet

## Device Matrix

| Model | Profile ID | Status | Notes |
| --- | --- | --- | --- |
| Fluke 376 FC | `fluke_376fc` | Supported | Shared CLI/desktop/SDK path exists. Real-hardware validation completed on March 28, 2026 for scan, live stream, SQLite logging, CSV/JSON export, and raw fixture capture against a physical meter. |

## Platform Matrix

| Platform | Status | Notes |
| --- | --- | --- |
| Windows | Experimental | Primary current dev environment. Desktop + CLI run in the venv. BLE behavior still needs repeated real-meter testing. |
| macOS | Experimental | CLI real-meter validation completed on March 28, 2026 on macOS 26.3 with Python 3.13. Desktop UI and packaged builds still need explicit validation. |
| Linux | Unknown | Core stack should be portable, but no launch/adapter validation is recorded yet. |

## Workflow Matrix

| Workflow | Status | Notes |
| --- | --- | --- |
| Battery Pack Check | Implemented | Desktop runner + workflow persistence in place. Needs real-meter exercise. |
| Solar Panel Test | Implemented | Data-defined workflow pack available. |
| Charger Output Check | Implemented | Data-defined workflow pack available. |
| Continuity Checklist | Implemented | Data-defined workflow pack available. |
