# LAN Live Web View

The `fluke serve` command turns the machine connected to the meter into a small
web server so a second person can watch the live reading from a phone browser on
the same network. It targets the classic two-person field scenario: one person
is at the electrical panel with the meter, a helper elsewhere watches the number.

There is **no cloud and no account**. Everything stays on the local network.

## Quick start

```powershell
fluke scan --timeout 10
fluke serve --device "<DEVICE_ID>" --profile fluke_376fc
```

On startup the command prints the reachable URLs (one per LAN interface) and a
scannable QR code for the primary URL:

```text
Live web view is running. Open on a phone on the same network:
  http://192.168.1.79:8765/
  http://127.0.0.1:8765/

  <ascii QR code>

Security: this is a trusted-LAN tool...
Press Ctrl+C to stop.
```

Open the URL (or scan the QR) on a phone that is on the same Wi-Fi / LAN.

## What the page shows

The page is a single self-contained HTML document (inline CSS and JS, no CDN or
external assets) so it works on job sites with no internet:

- the current reading in huge, high-contrast text readable from meters away
- unit and measurement type / mode
- min / max / avg since the server started
- connection status indicator (connecting / connected / reconnecting / disconnected)
- a stale-data indicator when readings stop arriving
- a rolling live chart drawn on a hand-rolled `<canvas>` (no external chart lib)

It is mobile-first: dark background for dim mechanical rooms, big type, and a
landscape-friendly layout.

## Options

| Option | Default | Purpose |
| --- | --- | --- |
| `--device` | required | BLE device id from `fluke scan` |
| `--profile` | `fluke_376fc` | Device profile id |
| `--port` | `8765` | TCP port to bind |
| `--host` | `0.0.0.0` | Interface to bind (all LAN interfaces) |
| `--token` | none | Optional shared secret; clients must pass `?token=...` |
| `--stale-after` | `3.0` | Seconds without a reading before data is flagged stale |
| `--read-only` | on | Read-only serving (the view never controls the meter) |
| `--duration` | `0` | Stop after N seconds; `0` runs until `Ctrl+C` |
| `--no-qr` | off | Skip the terminal QR code |
| `--log` | off | Also record readings to SQLite (see below) |

### Serving alongside a logging session

`--log` mirrors `fluke log`: it records every reading into SQLite while it
serves, reusing the same `SessionRecorder` and export plumbing.

```powershell
fluke serve --device "<DEVICE_ID>" --log --title "Panel check" --tags "field,helper" `
  --csv-output exports/panel.csv --json-output exports/panel.json
```

The session is finalized when serving stops, and exports (if requested) run
afterward, exactly like `fluke log`.

## Endpoints

| Path | Description |
| --- | --- |
| `GET /` | The self-contained live view page |
| `GET /ws` | WebSocket feed; each message is a full JSON state snapshot |
| `GET /api/status` | JSON snapshot: connection status, stats, staleness, latest reading, chart history |
| `GET /api/latest` | JSON with just the latest reading and staleness |
| `GET /healthz` | Liveness probe with connected client count |

The WebSocket pushes a snapshot immediately on connect and again on every new
reading or connection-status change. The browser client reconnects
automatically with backoff if the socket drops.

### Example

```powershell
curl http://192.168.1.79:8765/api/latest
```

```json
{
  "reading": {
    "timestamp_utc": "2026-07-08T18:20:01.123456+00:00",
    "value": 48.0,
    "unit": "V",
    "measurement_type": "voltage_dc",
    "status": "ok",
    "display_text": "48.00 V",
    "mode": "dc"
  },
  "stale": false,
  "seconds_since_reading": 0.12
}
```

## Security posture

This is a **trusted-LAN tool**. Read this before exposing it:

- It binds to `0.0.0.0` by default, so it is reachable from every device on the
  local network. Only run it on networks you trust.
- There is **no authentication in v1**. The optional `--token` flag adds a basic
  shared-secret gate: the page, WebSocket, and JSON endpoints all require a
  matching `?token=...` query parameter, and the printed URLs / QR embed it.
  A token in a query string is not strong auth (it can appear in logs); it is a
  convenience gate, not a security boundary.
- Traffic is plain HTTP; there is no TLS. Do not use this over untrusted links.
- The server is **read-only by construction**. It is a pure sink for the reading
  stream and never calls back into the device manager, so there is no endpoint
  through which the web page can control or reconfigure the meter.
- To restrict exposure to just the local machine, bind to loopback:
  `fluke serve --device ... --host 127.0.0.1`.

## Install

The web view is an optional extra:

```powershell
python -m pip install -e ".[web]"
```

or with requirements files:

```powershell
python -m pip install -r requirements-web.txt
```

The `.[full]` / `.[dev]` extras already include it. If `qrcode` is not
installed, the QR code is skipped gracefully and only the URLs are printed.

## Architecture

The feature follows the repo's shared-stack-first methodology:

- `packages/fluke_web/` is a shared package, not desktop- or CLI-specific code.
  - `state.py` — `LiveState`, an in-memory snapshot (latest reading, min/max/avg,
    sample count, staleness, rolling chart history). Decoupled from BLE.
  - `server.py` — `WebLiveServer`, an `aiohttp` app exposing the page, WebSocket,
    and JSON API. It exposes `on_reading()` / `set_connection_status()` as the
    device-manager-facing sink and broadcasts snapshots to WebSocket clients.
  - `page.py` — the self-contained HTML page.
  - `net.py` — LAN IP enumeration and URL building.
  - `qr.py` — optional ASCII QR rendering with graceful fallback.
- `apps/cli/commands/serve.py` is a thin surface that wires `DeviceManager`
  callbacks into the server and, with `--log`, into the existing
  `SessionRecorder`.

Because the server is a plain sink, the same object is exercised in tests by
feeding it readings from the fake BLE adapter with no network or hardware.
