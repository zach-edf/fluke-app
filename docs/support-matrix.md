# Support Matrix

This matrix is intentionally conservative. A model should only move to `Supported` after the parser, session flow, and at least one hardware validation pass are all in place.

## Status Levels

- `Supported`: profile exists, shared stack integration exists, and real hardware validation has been performed
- `Experimental`: profile exists or is in progress, but hardware coverage is incomplete or assumptions remain
- `Unknown`: no profile or validation yet

## Device Matrix

| Model | Profile ID | Status | Notes |
| --- | --- | --- | --- |
| Fluke 376 FC | `fluke_376fc` | Experimental | Shared CLI/desktop/SDK path exists. Non-hardware tests are strong. Real hardware validation still needs another pass after the current architecture rebuild. |

## Platform Matrix

| Platform | Status | Notes |
| --- | --- | --- |
| Windows | Experimental | Primary current dev environment. Desktop + CLI run in the venv. BLE behavior still needs repeated real-meter testing. |
| macOS | Unknown | Architecture is intended to support it through Bleak, but this repo state has not been validated recently. |
| Linux | Unknown | Core stack should be portable, but no launch/adapter validation is recorded yet. |

## Workflow Matrix

| Workflow | Status | Notes |
| --- | --- | --- |
| Battery Pack Check | Implemented | Desktop runner + workflow persistence in place. Needs real-meter exercise. |
| Solar Panel Test | Implemented | Data-defined workflow pack available. |
| Charger Output Check | Implemented | Data-defined workflow pack available. |
| Continuity Checklist | Implemented | Data-defined workflow pack available. |
