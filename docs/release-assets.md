# Release Assets Guide

This guide tracks the screenshots and packaging-facing assets that should stay current as the desktop UI evolves.

## Packaged Installer Artifacts

Releases ship prebuilt desktop installers so non-technical users can install
without Python. These are produced automatically by
`.github/workflows/release.yml` on a `v*` tag push and attached to the GitHub
Release:

- `FlukeCommunity-<version>-Setup.exe` — Windows Inno Setup installer
- `FlukeCommunity-windows.zip` — Windows one-dir bundle (portable, no installer)
- `FlukeCommunity-<version>.dmg` — macOS disk image (drag to Applications)

Build tooling and local build instructions live in
[`packaging/`](../packaging/README.md). The Windows path is verified locally;
the macOS path is CI-validated only until someone runs it on a Mac. Each CI
build runs `packaging/smoke_test.py`, which launches the packaged binary with
`--self-test` and fails the release if startup does not exit cleanly.

Notes for maintainers:

- The macOS build is currently unsigned / un-notarized. Document the
  right-click → **Open** first-launch step in release notes until signing is added.
- Update the `AppVersion` in `packaging/windows/installer.iss`, the version in
  `packaging/macos/build_macos.sh`, and `pyproject.toml` together when cutting a
  release.

## Current Audit

The written docs are mostly up to date, but the screenshot set is no longer representative of the current desktop app.

What is currently present:

- `README.md` shows only:
  - `Home`
  - `Live Reading`
  - `Workflows`
- `docs/fluke-app-screenshots/` includes older captures for:
  - discovery
  - home
  - live reading
  - session comparison
  - session with markers
  - settings
  - workflows

What is missing from the current screenshot set:

- the richer `Live Reading` page with:
  - device logging settings
  - device-memory actions
  - improved connection/reconnect status
- the `Session` page device-memory browser:
  - browse
  - preview rows
  - import selected / import all / import and clear
- the `Settings` page diagnostics and device info panel:
  - family
  - variant
  - capabilities
  - services
  - raw fixture export
- the advanced clamp live panel:
  - primary and secondary readings
  - family mode badges

## Recommended Screenshot Set

These are the screenshots worth shipping for the next release.

### README set

Use a compact set here. Newcomers should understand the app in under one minute.

1. `readme-device-discovery-connected.png`
   - `Device Discovery`
   - one supported meter selected
   - clear support/profile/capability columns visible

2. `readme-live-reading-logging-settings.png`
   - `Live Reading`
   - connected meter
   - live chart visible
   - logging settings visible
   - at least one alert/session control visible

3. `readme-session-device-memory.png`
   - `Session`
   - recent sessions visible
   - device-memory browser populated
   - import buttons visible

4. `readme-workflows.png`
   - `Workflows`
   - one realistic workflow selected
   - current step and run history visible

### Desktop guide set

These should support the user guide more directly.

1. `desktop-home-overview.png`
2. `desktop-device-discovery-connected.png`
3. `desktop-live-reading-standard.png`
4. `desktop-live-reading-advanced-clamp.png`
5. `desktop-session-replay.png`
6. `desktop-session-device-memory-browser.png`
7. `desktop-workflows-runner.png`
8. `desktop-settings-diagnostics.png`

## Capture Rules

To keep screenshots consistent:

- use the `Fluke` theme
- maximize the window at a common desktop resolution
- prefer a clean seeded database with realistic but non-sensitive sample data
- show a connected device where relevant
- avoid empty states unless the screenshot is explicitly about an empty state
- use readable session titles and notes
- keep exported filenames and local paths out of the visible frame where possible

Recommended visible scenarios:

- one supported legacy clamp meter connected
- one imported saved-memory session visible
- one workflow with realistic capture history
- one advanced clamp live view if hardware/fixtures are available

## Where To Update References

When replacing screenshots, update these locations first:

- `README.md`
- `docs/desktop-guide.md` if screenshots are added inline
- `docs/README.md` if the screenshot directory naming changes

## Practical Release Checklist

Before cutting a release:

1. Verify the screenshot filenames in `README.md` still match real files.
2. Re-capture any page that gained new visible controls.
3. Confirm the `Session` screenshot includes the device-memory browser, since that is now a headline feature.
4. Confirm the `Settings` screenshot includes diagnostics/device info, since the tab is no longer just theme/export controls.
5. If advanced clamp support is being advertised publicly, capture one dual-reading screenshot before release.
6. Bump the version in `pyproject.toml`, `packaging/windows/installer.iss`, and `packaging/macos/build_macos.sh` so the installer artifacts are named correctly.
7. Push the `v<version>` tag and confirm the `Release` workflow built, smoke-tested, and attached the Windows and macOS installers.

## Screenshot Generation Script

The repo now includes a deterministic screenshot generator for the main README/desktop-release images:

- `scripts/generate_release_screenshots.py`

It generates the current fake-device screenshots into:

- `docs/fluke-app-screenshots/readme-device-discovery-connected.png`
- `docs/fluke-app-screenshots/readme-live-reading-logging-settings.png`
- `docs/fluke-app-screenshots/readme-session-device-memory.png`
- `docs/fluke-app-screenshots/readme-workflows.png`
- `docs/fluke-app-screenshots/desktop-home-overview.png`
- `docs/fluke-app-screenshots/desktop-device-discovery-connected.png`
- `docs/fluke-app-screenshots/desktop-live-reading-standard.png`
- `docs/fluke-app-screenshots/desktop-live-reading-advanced-clamp.png`
- `docs/fluke-app-screenshots/desktop-session-replay.png`
- `docs/fluke-app-screenshots/desktop-session-device-memory-browser.png`
- `docs/fluke-app-screenshots/desktop-workflows-runner.png`
- `docs/fluke-app-screenshots/desktop-settings-diagnostics.png`

Run it with the desktop-capable interpreter, for example on Windows:

```powershell
.\.venv\Scripts\python.exe scripts\generate_release_screenshots.py
```
