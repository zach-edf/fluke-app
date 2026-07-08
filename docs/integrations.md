# Integrations Guide

This guide covers the optional MQTT publishing integration, including Home
Assistant MQTT Discovery. Spoken readings (TTS) are documented in the
[CLI guide](cli-guide.md#spoken-readings-tts) and
[desktop guide](desktop-guide.md).

MQTT is exposed through the CLI (`fluke stream`, `fluke log`) and the Python SDK
(`FlukeClient.attach_publisher`). The desktop app does not currently expose MQTT
configuration; use the CLI or SDK for broker publishing.

## Installation

MQTT publishing depends on `paho-mqtt`, which is an optional extra:

```bash
pip install -e ".[mqtt]"
```

or, if you use requirements files:

```bash
pip install -r requirements-mqtt.txt
```

`paho-mqtt` is also included in the `[full]` and `[dev]` extras.

## What gets published

When publishing is enabled the meter is connected to the broker and the
following topics are used (with the default base topic `fluke` and a device id
that is slugified to lowercase with non-alphanumeric characters replaced by
underscores):

| Topic | Payload | Retained | Notes |
| --- | --- | --- | --- |
| `fluke/<device_id>/reading` | JSON reading | no (unless `--mqtt-retain`) | one message per reading |
| `fluke/<device_id>/availability` | `online` / `offline` | yes | backed by an MQTT Last Will (LWT) |
| `homeassistant/sensor/<device_id>/<key>/config` | HA discovery config | yes | published on connect when discovery is enabled |

The availability topic uses the broker's Last Will and Testament, so if the
publisher disconnects uncleanly the broker automatically marks the meter
`offline`.

### Reading payload

```json
{
  "timestamp": "2026-07-08T12:00:00+00:00",
  "value": 121.3,
  "unit": "V",
  "measurement_type": "voltage_ac",
  "status": "ok",
  "display_text": "121.3 V",
  "mode": "ac",
  "device_id": "meter-1"
}
```

## CLI usage

```bash
fluke stream --device "<DEVICE_ID>" --mqtt-host 192.168.1.10 --mqtt-topic fluke
fluke log    --device "<DEVICE_ID>" --duration 60 \
  --mqtt-host 192.168.1.10 --mqtt-username fluke --mqtt-password secret --mqtt-tls
```

Relevant options:

- `--mqtt-host` (enables publishing), `--mqtt-port` (default 1883)
- `--mqtt-username`, `--mqtt-password`, `--mqtt-tls`
- `--mqtt-topic` (base topic, default `fluke`)
- `--mqtt-qos {0,1,2}`, `--mqtt-retain`
- `--mqtt-no-discovery` (disable Home Assistant discovery)

If the broker is unreachable at connect time, the command prints a warning and
continues streaming/logging without MQTT rather than failing.

## SDK usage

```python
import asyncio

from fluke_sdk import FlukeClient
from fluke_app import MqttConfig, MqttPublisher


async def main() -> None:
    client = FlukeClient()
    publisher = MqttPublisher(MqttConfig(host="192.168.1.10", base_topic="fluke"))
    client.attach_publisher(publisher)

    devices = await client.scan(timeout_s=5.0)
    await client.connect(devices[0].device_id)  # publisher.connect() is called for you

    async for reading in client.stream_readings():
        print(reading.display_text)  # each reading is also published to MQTT

    await client.close()  # publisher.disconnect() is called for you


asyncio.run(main())
```

Any object exposing `connect(device_id, device=...)`, `publish_reading(reading)`,
and `disconnect()` can be attached the same way.

## Home Assistant MQTT Discovery

When discovery is enabled (the default), the publisher sends retained config
messages under the `homeassistant/` prefix on connect. Home Assistant then
creates the meter as a device with four sensors:

- **Reading Value** (`value`) — numeric value, unit delivered via template
- **Reading Unit** (`unit`) — current unit string
- **Measurement Type** (`measurement_type`) — e.g. `voltage_ac`
- **Reading Display** (`display`) — the raw display text

Each config message includes a shared `device` block so all four sensors group
under one device, plus `state_topic`, `value_template`, and the availability
topic:

```json
{
  "name": "Reading Value",
  "unique_id": "meter_1_value",
  "state_topic": "fluke/meter_1/reading",
  "value_template": "{{ value_json.value }}",
  "unit_of_measurement": "{{ value_json.unit }}",
  "availability_topic": "fluke/meter_1/availability",
  "payload_available": "online",
  "payload_not_available": "offline",
  "device": {
    "identifiers": ["fluke_meter_1"],
    "name": "Bench Meter",
    "manufacturer": "Fluke (community)",
    "model": "Fluke 376 FC"
  }
}
```

Because the meter changes units at runtime, the unit is delivered by template
rather than a fixed `unit_of_measurement`.

### Prerequisites

1. An MQTT broker (for example Mosquitto or the Home Assistant Mosquitto add-on).
2. The [MQTT integration](https://www.home-assistant.io/integrations/mqtt/)
   enabled in Home Assistant, pointed at the same broker.
3. The default discovery prefix `homeassistant` (which HA uses by default).

Start publishing and the meter should appear under
**Settings -> Devices & Services -> MQTT** within a few seconds.

### Manual configuration (optional)

If you prefer static YAML sensors instead of discovery, disable discovery with
`--mqtt-no-discovery` and add something like:

```yaml
mqtt:
  sensor:
    - name: "Fluke Reading Value"
      state_topic: "fluke/meter_1/reading"
      value_template: "{{ value_json.value }}"
      unit_of_measurement: "V"
      availability_topic: "fluke/meter_1/availability"
      payload_available: "online"
      payload_not_available: "offline"
    - name: "Fluke Measurement Type"
      state_topic: "fluke/meter_1/reading"
      value_template: "{{ value_json.measurement_type }}"
```

## Troubleshooting

- **No sensors appear**: confirm the HA MQTT integration points at the same
  broker, and that the discovery prefix is `homeassistant`.
- **Sensors show unavailable**: check the `fluke/<device_id>/availability` topic;
  it should read `online` while publishing and `offline` after disconnect.
- **Connection refused**: verify host/port/credentials and, for TLS brokers,
  that `--mqtt-tls` is set.
- **`paho-mqtt` not installed**: install the extra with `pip install -e ".[mqtt]"`.

## Related guides

- [CLI Guide](cli-guide.md)
- [Desktop Guide](desktop-guide.md)
- [SDK Guide](sdk-guide.md)
