# Getting Started

This guide is for a brand-new user who wants to install the project and successfully use it for the first time.

## What This Project Includes

The repo exposes the same Fluke meter functionality through three user-facing surfaces:

- a desktop app built with PySide6
- a command-line interface
- a Python SDK

All three sit on top of the same shared protocol, BLE, persistence, export, and workflow layers.

## What You Can Do

With the current codebase, a user can:

- scan for nearby BLE-enabled Fluke meters
- connect and stream live readings
- record sessions into SQLite
- add markers and notes
- replay and compare prior sessions
- export session data and charts
- run guided workflows
- create new workflow definitions in the desktop app
- inspect supported device profiles and optional plugins
- capture raw fixtures and export debug bundles for diagnostics

## Current In-Tree Device Focus

The main built-in device path in the current repo is the Fluke 376 FC.

The architecture supports additional profiles and plugin-contributed workflows, but the 376 FC remains the primary built-in focus.

## Requirements

Minimum requirements:

- Python 3.11 or newer
- a BLE-capable host system
- a virtual environment is strongly recommended

Desktop app requirements:

- `PySide6`
- `bleak`

## Choosing The Right Install

### Packaged installer (no Python required)

If you are an end user (for example a tradesperson) who just wants the desktop
app, use a prebuilt installer instead of the Python paths below. You do not need
Python, a virtual environment, or the command line.

1. Go to the project's [Releases](../../releases) page.
2. Download the asset for your platform:
   - Windows: `FlukeCommunity-<version>-Setup.exe`
   - macOS: `FlukeCommunity-<version>.dmg`
3. Install and launch:
   - Windows: run the setup executable (per-user install, no admin rights) and
     start `Fluke Community` from the Start menu.
   - macOS: open the `.dmg`, drag `Fluke Community` into `Applications`, then
     right-click the app and choose **Open** the first time (the build is not
     yet code-signed).

The database and exports still live in the standard per-user locations described
in [Where Data Goes](#where-data-goes).

The Python-based installs below are for developers, contributors, and anyone who
also wants the CLI or SDK. Maintainers building the installers should read
[../packaging/README.md](../packaging/README.md).

### Full install

Use this if you want:

- the desktop app
- the CLI
- the SDK
- plotting and contributor extras

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-full.txt
python -m pip install -e .
```

### Minimal install

Use this if you only need:

- the CLI
- the SDK

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

## Launching The App

After the editable install, the project provides these entry points:

- `fluke`
- `fluke-cli`
- `fluke-desktop`

If you prefer module entry points instead:

- `python -m apps.cli.main`
- `python -m apps.desktop.main`

### Start the desktop app

```powershell
fluke-desktop
```

or:

```powershell
python -m apps.desktop.main
```

### Check the CLI

```powershell
fluke --help
```

## First Desktop Run

Recommended path for a new user:

1. Launch the desktop app.
2. Open `Device Discovery`.
3. Click `Scan`.
4. Select a meter from the list.
5. Click `Connect`.
6. Open `Live Reading`.
7. Confirm that values, unit, and measurement type are updating.
8. Enter a session title and optional session notes.
9. Click `Start Logging`.
10. Add a marker if you want to annotate an event during the session.
11. Click `Stop Logging`.
12. Open `Session` to review the saved run and export it if needed.
13. Open `Workflows` if you want guided measurement steps or workflow authoring.

For a full desktop walkthrough, see [Desktop User Guide](desktop-guide.md).

## First CLI Run

Recommended path for a new CLI user:

1. Scan for devices.
2. Stream readings to confirm the BLE path works.
3. Record a short session.
4. Export the session.
5. List available workflows.

### 1. Scan

```powershell
fluke scan --timeout 10
```

### 2. Stream

```powershell
fluke stream --device "<DEVICE_ID>" --profile fluke_376fc
```

### 3. Record a short session

```powershell
fluke log `
  --device "<DEVICE_ID>" `
  --profile fluke_376fc `
  --duration 15 `
  --title "First session"
```

### 4. List recent sessions

```powershell
fluke sessions list
```

### 5. Export a session

```powershell
fluke sessions export --session "<SESSION_ID>" --format json --output exports/session.json
```

### 6. List workflows

```powershell
fluke workflow list
```

For the full CLI reference, see [CLI Guide](cli-guide.md).

## First SDK Run

If you want to script against the stack in Python:

```python
import asyncio

from fluke_sdk import FlukeClient


async def main() -> None:
    client = FlukeClient()
    devices = await client.scan(timeout_s=5.0)
    if not devices:
        print("No devices found.")
        return

    await client.connect(devices[0].device_id)

    async for reading in client.stream_readings():
        print(reading.display_text)
        break

    await client.close()


asyncio.run(main())
```

For the full SDK walkthrough, see [SDK Guide](sdk-guide.md).

## Where Data Goes

By default, the CLI uses a platform-specific SQLite database path.

- Windows: `%LOCALAPPDATA%/fluke-community/fluke.db`
- macOS: `~/Library/Application Support/fluke-community/fluke.db`
- Linux: `~/.local/share/fluke-community/fluke.db`

The desktop app also uses the shared default database path at runtime.

The desktop export directory defaults to `exports` unless you change it in the `Settings` tab during the current app session.

For more detail, see [Data and Exports Guide](data-and-exports.md).

## Suggested Learning Path

If you want to learn all of the user-facing features in order:

1. [Getting Started](getting-started.md)
2. [Desktop User Guide](desktop-guide.md)
3. [Workflows Page Guide](workflows-page.md)
4. [Data and Exports Guide](data-and-exports.md)
5. [CLI Guide](cli-guide.md)
6. [SDK Guide](sdk-guide.md)

## Common First-Run Problems

### No devices found during scan

Check:

- the meter is powered on
- BLE is enabled on the host
- the device is in range
- another application is not already holding the BLE session

### Desktop app launches but cannot connect

Check:

- the full dependency set is installed
- `bleak` is available in the active virtual environment
- the selected device profile matches the target device

### The desktop app opens but charts do not render

Check:

- `PySide6` is installed
- the desktop dependency set was installed from `requirements-full.txt` or an equivalent requirements file

### Session export or workflow report export does not appear where expected

Check:

- the current export directory in the desktop `Settings` tab
- the explicit output path you passed on the CLI

## Next Guides

- [Desktop User Guide](desktop-guide.md)
- [CLI Guide](cli-guide.md)
- [Workflows Page Guide](workflows-page.md)
- [Data and Exports Guide](data-and-exports.md)
