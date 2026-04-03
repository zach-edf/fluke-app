# Testing Guide

This guide explains the current automated test strategy and how contributors should verify changes.

## Testing Philosophy

The repo is designed so most meaningful changes can be tested without hardware.

Preferred strategy:

- use unit tests for deterministic logic
- use fake adapters and replay helpers for connection/stream behavior
- use fixtures when protocol decoding needs real raw input
- keep hardware validation as a final confidence pass, not the only validation path

## Current Test Layout

The main automated suite lives under [tests/unit](../../tests/unit).

Current coverage areas include:

- CLI entry points
- export and capture paths
- debug bundle generation
- desktop presenter behavior
- desktop views
- desktop chart widget behavior
- fake adapter and stream behavior
- fixture capture tooling
- Fluke 376 FC profile parsing
- logging flow
- plugin loader behavior
- SDK client behavior
- statistics helpers
- store path behavior
- workflow catalog behavior
- workflow runner behavior

## Core Test Commands

Install expectations:

- minimal CLI/SDK verification works with `python -m pip install -e .`
- the full suite requires the desktop/full dependency set because desktop tests import `PySide6`
- the supported contributor/CI install is `python -m pip install -e ".[dev]"`

### Full unit suite

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

### Compile check

```powershell
python -m compileall apps packages tests
```

### Minimal CLI/SDK suite

```powershell
python -m unittest tests.unit.test_cli_main tests.unit.test_sdk_client tests.unit.test_fluke_376fc_profile tests.unit.test_fake_adapter_and_stream tests.unit.test_logging_flow tests.unit.test_workflow_catalog tests.unit.test_workflow_runner tests.unit.test_capture_export tests.unit.test_debug_bundle tests.unit.test_fixture_capture_tool tests.unit.test_plugin_loader tests.unit.test_statistics tests.unit.test_store_paths
```

The compile check is useful for catching:

- syntax errors
- import breakage
- accidental bad edits in large refactors

## Targeted Test Runs

Use targeted runs when you are changing a specific area and want faster iteration.

### Desktop presenter and views

```powershell
python -m unittest tests.unit.test_desktop_presenter tests.unit.test_desktop_views tests.unit.test_desktop_chart_widget
```

### Workflows

```powershell
python -m unittest tests.unit.test_workflow_catalog tests.unit.test_workflow_runner
```

### CLI

```powershell
python -m unittest tests.unit.test_cli_main
```

### SDK

```powershell
python -m unittest tests.unit.test_sdk_client
```

### Plugins

```powershell
python -m unittest tests.unit.test_plugin_loader
```

### Profile parsing

```powershell
python -m unittest tests.unit.test_fluke_376fc_profile tests.unit.test_fake_adapter_and_stream
```

### Export and diagnostics

```powershell
python -m unittest tests.unit.test_capture_export tests.unit.test_debug_bundle tests.unit.test_fixture_capture_tool
```

## What To Run For Common Change Types

### Desktop-only UI change

Minimum:

- `tests.unit.test_desktop_views`
- `tests.unit.test_desktop_presenter`

If chart behavior or theme behavior changed:

- `tests.unit.test_desktop_chart_widget`

### Workflow change

Minimum:

- `tests.unit.test_workflow_catalog`
- `tests.unit.test_workflow_runner`

If desktop workflow UI changed:

- `tests.unit.test_desktop_views`
- `tests.unit.test_desktop_presenter`

### CLI command change

Minimum:

- `tests.unit.test_cli_main`

If the command touches exports, workflows, or plugins, include their focused test modules too.

### SDK change

Minimum:

- `tests.unit.test_sdk_client`

### Parser or profile change

Minimum:

- profile-specific parsing tests
- fake adapter / stream tests

### Store or export change

Minimum:

- export tests
- any store path or persistence tests
- affected CLI or desktop tests if behavior surfaced to users changed

## Hardware-Free Validation

The project already includes test support for:

- fake BLE adapters
- replay-driven parser validation
- fixture capture and replay

Use those before reaching for a real meter unless the bug is clearly runtime-transport specific.

## Fixture-Based Validation

When you need representative real data:

1. capture a raw fixture from hardware
2. commit it if appropriate for the repo and review context
3. add parser/replay coverage around it

See [Fixtures and Debug Bundles](fixtures-and-debug.md).

## Manual Verification Expectations

Some changes still deserve manual checks even if tests pass.

Examples:

- desktop layout or interaction changes
- theme changes
- workflow builder behavior
- alert behavior
- reconnect UX

Typical manual verification notes should mention:

- what surface was exercised
- what scenario was tested
- whether a real meter or fake path was used

## Documentation Changes

Docs-only changes typically do not need a test run unless the doc references commands or files you want to spot-check manually.

## Related Guides

- [Development Workflow](development-workflow.md)
- [Fixtures and Debug Bundles](fixtures-and-debug.md)
- [New Device Profile Guide](new-device-profile.md)
