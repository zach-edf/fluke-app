# Packaging the Fluke Community desktop app

This directory contains everything needed to build standalone desktop
installers so non-technical users can install the app without touching Python.

The build tool is **PyInstaller**. It produces a self-contained one-dir bundle
that includes the Python runtime, PySide6/Qt, the `bleak` BLE backend for the
target platform, and the app's bundled data (`workflows/`, `plugins/`, and the
built-in workflow JSON in `fluke_app.workflows`).

## Why PyInstaller

PyInstaller was chosen over alternatives (briefcase, cx_Freeze, Nuitka) because:

- PySide6 and `bleak` both have first-class, maintained PyInstaller hooks
  (`pyinstaller-hooks-contrib`), including the Windows `winrt` projection and
  macOS CoreBluetooth backends that BLE relies on.
- A single `.spec` file drives both Windows and macOS builds.
- It integrates cleanly with the existing GitHub Actions CI.

No concrete blocker was found. The Windows build is verified locally; the macOS
build path is CI-validated only (see below).

## Contents

| Path | Purpose |
| --- | --- |
| `fluke-desktop.spec` | Cross-platform PyInstaller spec (entry: `apps/desktop/main.py`). |
| `smoke_test.py` | Launches the packaged binary with `--self-test` and checks it exits 0. |
| `windows/build_windows.ps1` | Builds the Windows bundle, runs the smoke test, compiles the installer. |
| `windows/installer.iss` | Inno Setup script that wraps the one-dir build into a per-user installer. |
| `macos/build_macos.sh` | Builds the `.app` bundle, runs the smoke test, produces a `.dmg`. |
| `icons/` | Place `fluke.ico` / `fluke.icns` here (optional; build tolerates absence). |

## Prerequisites

Install the app's full/dev dependencies plus PyInstaller into the environment
you build from:

```bash
python -m pip install -e ".[dev]"
python -m pip install pyinstaller
```

- **Windows installer** additionally needs [Inno Setup 6](https://jrsoftware.org/isdl.php)
  (`ISCC.exe` on `PATH`, or installed at the default location).
- **macOS `.dmg`** uses `hdiutil`, which ships with macOS.

## The `--self-test` flag

The desktop app accepts a `--self-test` flag (or `FLUKE_SELF_TEST=1`). It
initializes the full service stack -- SQLite store under the platform app-data
dir, the BLE adapter import, bundled workflows, and plugin discovery -- then
prints a status line and exits 0. It never opens a window and needs no BLE
hardware, which makes it the basis for the packaged smoke test in CI.

```bash
# From source:
python -m apps.desktop.main --self-test
# Against a packaged build:
python packaging/smoke_test.py            # auto-locates dist/
python packaging/smoke_test.py path/to/FlukeCommunity.exe
```

## Building on Windows

```powershell
# From the repo root, in your build venv:
pwsh packaging/windows/build_windows.ps1
# Skip the installer (bundle + smoke test only):
pwsh packaging/windows/build_windows.ps1 -SkipInstaller
```

Outputs:

- `dist/FlukeCommunity/` -- the one-dir bundle (`FlukeCommunity.exe` + `_internal/`)
- `dist/installer/FlukeCommunity-0.1.0-Setup.exe` -- the Inno Setup installer

Or invoke PyInstaller directly:

```powershell
python -m PyInstaller packaging/fluke-desktop.spec --noconfirm --clean
python packaging/smoke_test.py
```

## Building on macOS (CI-validated only)

> This path has been written but not executed on a local macOS machine by the
> author. It is exercised by the `build-macos` job in
> `.github/workflows/release.yml`. Treat local runs as the first validation.

```bash
bash packaging/macos/build_macos.sh          # .app + .dmg
bash packaging/macos/build_macos.sh --no-dmg # .app only
```

Outputs:

- `dist/FlukeCommunity.app` -- the app bundle
- `dist/FlukeCommunity-0.1.0.dmg` -- the drag-to-Applications disk image

The bundle is **unsigned and un-notarized**, so on first launch users must
right-click the app and choose **Open** to bypass Gatekeeper. Code signing and
notarization are a follow-up (they require an Apple Developer certificate).

## How bundled data is resolved at runtime

PyInstaller unpacks bundled data under `sys._MEIPASS`. The app resolves the
`workflows/` and `plugins/` directories through
`fluke_core.paths.bundled_data_dir(...)`, which returns the bundle location when
frozen and falls back to the source-tree layout otherwise. This is why the
build ships those directories as `datas` in the spec. The default SQLite path
(`fluke_core` / `apps.cli.runtime.default_database_path`) already targets the
platform app-data dir and does not depend on the current working directory, so
it works unchanged in packaged mode.

## Release automation

Pushing a `v*` tag triggers `.github/workflows/release.yml`, which builds the
Windows and macOS artifacts, runs the smoke test on each, and attaches them to a
GitHub Release. The workflow can also be dispatched manually for a dry run
(builds + smoke tests, no Release published).
