# Contributing

This project is intentionally structured so protocol work, app workflows, desktop UI, CLI, and SDK all share the same core services. Contributions are most useful when they keep that shared architecture intact.

This is an unofficial community project and is not affiliated with or endorsed by Fluke Corporation.

## Principles

- Fix the shared layer first, then surface it in CLI/Desktop/SDK.
- Keep device-specific logic in profiles, not in presenters or CLI commands.
- Prefer hardware-free tests with fake adapters and recorded fixtures.

Start with the contributor docs hub at [docs/developer/README.md](docs/developer/README.md) for the fuller development workflow and testing guides.

## Local Setup

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

Run the test suite:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe -m compileall apps packages tests
```

If you only need the CLI or SDK path, a minimal install is enough:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

Contributor note:

- the full automated suite imports `PySide6`, so `.[dev]` or `requirements-full.txt` is the supported test environment
- the repository also keeps the `requirements*.txt` files for users who prefer explicit dependency sets over package extras

## Where To Put Changes

- `packages/fluke_core`: domain models, enums, statistics, workflow models
- `packages/fluke_protocol`: profile matching and packet decoding
- `packages/fluke_app`: orchestration, session recording, workflows, debug bundle
- `packages/fluke_store`: SQLite schema and repositories
- `apps/cli`: user-facing CLI commands
- `apps/desktop`: desktop presenter/view/widget layer
- `packages/fluke_testing`: fake adapters, replay helpers, fixture capture utilities
- `plugins/`: optional extension boundary for contributed profiles and workflow packs

## New Device Profiles

Follow [docs/developer/new-device-profile.md](docs/developer/new-device-profile.md).

The expected flow is:

1. Capture raw fixture data from a real meter.
2. Add or update a `DeviceProfile`.
3. Add parser/unit tests and replay tests.
4. Register the new profile through the plugin boundary if it is experimental.
5. Update the support matrix and contributor docs.

## Fixtures And Bug Reports

- Raw fixture capture: [docs/developer/fixtures-and-debug.md](docs/developer/fixtures-and-debug.md)
- Debug bundle export: [docs/developer/fixtures-and-debug.md](docs/developer/fixtures-and-debug.md)
- Issue templates live under `.github/ISSUE_TEMPLATE/`

## Pull Request Expectations

- Include tests for behavioral changes.
- Call out hardware assumptions explicitly.
- Prefer absolute dates and version numbers in bug notes when timing matters.
- Do not remove user data or rewrite schema history without clear migration notes.
