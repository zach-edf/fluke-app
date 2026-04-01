# SDK Guide

This guide explains how to use the Python SDK directly.

## Overview

The SDK exposes the shared Fluke stack to Python code so you can:

- scan for devices
- connect to a device
- stream normalized readings
- inspect connection state
- subscribe to reading callbacks
- integrate the BLE path into custom scripts or applications

The main public entry point is:

- `FlukeClient`

## Installation

For SDK usage you need the shared runtime and BLE dependencies available in your environment.

Minimal install:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
```

## Public API Surface

The current SDK exports:

- `FlukeClient`
- `ReadingStream`

### `FlukeClient`

Key methods:

- `scan(timeout_s=5.0)`
- `connect(device_id, profile_id=None)`
- `disconnect()`
- `close()`
- `state()`
- `latest_reading()`
- `on_reading(handler)`
- `stream_readings()`

## Basic Example

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

    try:
        async for reading in client.stream_readings():
            print(reading.display_text)
            break
    finally:
        await client.close()


asyncio.run(main())
```

## Typical Usage Pattern

The normal SDK flow is:

1. Create a `FlukeClient`.
2. Call `scan()`.
3. Choose a device id.
4. Call `connect()`.
5. Consume readings either through `stream_readings()` or `on_reading()`.
6. Call `disconnect()` or `close()` when finished.

## Streaming Readings

`stream_readings()` is an async iterator.

Example:

```python
async for reading in client.stream_readings():
    print(reading.display_text)
```

Behavior:

- the first call starts streaming if it has not already started
- readings are yielded as normalized `Reading` domain objects
- the iterator stops when the internal stream is closed

## Callback Style

If you want push-style integration, use `on_reading()`.

Example:

```python
def handle_reading(reading):
    print(reading.display_text)


client.on_reading(handle_reading)
```

This is useful when integrating the client into your own event-handling or persistence layer.

## Latest Reading and Connection State

`latest_reading()` returns the most recent normalized reading seen by the client, if one exists.

`state()` returns the current connection state from the shared device manager.

These are useful for:

- polling integrations
- lightweight status checks
- coordination with your own UI or task logic

## Recording Sessions From SDK Code

The SDK focuses on device communication, not a complete high-level logging facade.

If you want to persist sessions from Python code, compose it with the shared app services, such as:

- `FlukeStore`
- `SessionRecorder`
- `ExportService`
- `new_session()`

There is already an example in:

- [packages/fluke_sdk/examples/log_to_csv.py](../packages/fluke_sdk/examples/log_to_csv.py)

That example shows how to:

- connect with `FlukeClient`
- record readings into SQLite
- stop the session
- export CSV and JSON

## Example Files

Useful SDK examples in the repo:

- [basic_stream.py](../packages/fluke_sdk/examples/basic_stream.py)
- [log_to_csv.py](../packages/fluke_sdk/examples/log_to_csv.py)

## Profile Registry Behavior

By default, `FlukeClient` builds its profile registry through the same plugin-aware registry loader used elsewhere in the project.

That means the SDK can pick up:

- built-in profiles
- plugin-contributed profiles

unless you explicitly provide your own profile registry or device manager.

## Advanced Construction

`FlukeClient` can be initialized with custom dependencies:

- `ble_adapter`
- `profile_registry`
- `device_manager`

This is useful for:

- testing
- fake adapters
- custom registry wiring
- embedding the SDK into a larger application

## Cleanup

Always close the client when finished.

Preferred pattern:

```python
try:
    ...
finally:
    await client.close()
```

`close()` internally suppresses disconnect errors and is the safest general cleanup call.

## When To Use The SDK Instead Of The CLI Or Desktop

Use the SDK when you need:

- custom Python automation
- programmatic scanning and connection logic
- direct access to normalized `Reading` objects
- integration into your own application or test harness

Use the CLI when you need:

- quick terminal workflows
- session capture without writing Python code
- diagnostics exports and fixture capture

Use the desktop app when you need:

- charts
- session replay
- manual markers
- workflow authoring
- workflow run review

## Related Guides

- [Getting Started](getting-started.md)
- [CLI Guide](cli-guide.md)
- [Desktop User Guide](desktop-guide.md)
- [Data and Exports Guide](data-and-exports.md)
