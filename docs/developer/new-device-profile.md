# Adding A New Device Profile

This project now has an explicit plugin boundary so a contributor can add an experimental profile without editing the desktop UI.

## Goal

A new profile should:

- match the device during scan/connect
- decode notifications into canonical `Reading` objects
- work in `fluke stream`, session logging, desktop live view, exports, and workflows

## Recommended Workflow

1. Capture real raw notifications from the target device.

PowerShell:

```powershell
.\.venv\Scripts\python.exe -m apps.cli.main fixtures capture `
  --device "<DEVICE_ID>" `
  --profile fluke_376fc `
  --duration 10 `
  --output fixtures/sample.json
```

2. Copy the example plugin template from `plugins/examples/example_profile_plugin/`.

3. Implement a `DeviceProfile` subclass in the plugin module.

4. Register the profile through the plugin manifest.

5. Add parser and replay tests under `tests/unit/`.

6. Update [docs/support-matrix.md](../support-matrix.md).

## Minimum Plugin Shape

`manifest.json`:

```json
{
  "plugin_id": "my_experimental_meter",
  "name": "My Experimental Meter",
  "version": "0.1.0",
  "module": "profile.py",
  "callable": "register_plugin",
  "enabled": true
}
```

`profile.py` must export the registration callable.

## Decoder Expectations

Keep the decoder focused on:

- profile matching
- characteristic selection
- payload parsing
- canonical `Reading` output

Avoid putting workflow logic, desktop behavior, or persistence behavior in the profile.

## Tests To Add

- parser unit tests
- replay tests using `FakeBleAdapter` or packet fixtures
- workflow compatibility if the profile introduces a new measurement type expectation

## Review Checklist

- unique `profile_id`
- clear capability list
- no desktop-specific assumptions
- tests pass without hardware
- fixture sample committed when allowed
