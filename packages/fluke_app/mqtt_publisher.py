"""Optional MQTT publishing of live readings.

``MqttPublisher`` is a thin shared service that publishes each normalized
``Reading`` as JSON to ``<base>/<device_id>/reading`` and maintains an
availability topic (``online`` / ``offline``) backed by an MQTT Last Will and
Testament so consumers can tell when the meter drops off.

It also implements Home Assistant MQTT Discovery: on connect it publishes
retained ``homeassistant/sensor/.../config`` messages describing a value / unit /
measurement-type sensor set with a shared device block, so the meter appears in
Home Assistant automatically.

The paho client is injected (or lazily built), so the whole service is testable
against a fake client without a live broker.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading


@dataclass(frozen=True, slots=True)
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    use_tls: bool = False
    base_topic: str = "fluke"
    client_id: str = "fluke-community"
    qos: int = 0
    retain: bool = False
    keepalive: int = 60
    # Home Assistant MQTT Discovery
    discovery: bool = True
    discovery_prefix: str = "homeassistant"

    def reading_topic(self, device_id: str) -> str:
        return f"{self.base_topic}/{_slug(device_id)}/reading"

    def availability_topic(self, device_id: str) -> str:
        return f"{self.base_topic}/{_slug(device_id)}/availability"


class MqttClientProtocol(Protocol):
    """Subset of ``paho.mqtt.client.Client`` the publisher relies on."""

    def username_pw_set(self, username: str | None, password: str | None = None) -> Any: ...
    def tls_set(self, *args: Any, **kwargs: Any) -> Any: ...
    def will_set(self, topic: str, payload: Any = None, qos: int = 0, retain: bool = False) -> Any: ...
    def connect(self, host: str, port: int = 1883, keepalive: int = 60) -> Any: ...
    def loop_start(self) -> Any: ...
    def loop_stop(self) -> Any: ...
    def publish(self, topic: str, payload: Any = None, qos: int = 0, retain: bool = False) -> Any: ...
    def disconnect(self) -> Any: ...


class MqttPublisher:
    def __init__(
        self,
        config: MqttConfig,
        client: MqttClientProtocol | None = None,
        *,
        client_factory: Callable[[MqttConfig], MqttClientProtocol] | None = None,
    ) -> None:
        self._config = config
        self._client_factory = client_factory or _build_paho_client
        self._client = client
        self._connected = False
        self._device_id: str | None = None
        self._announced_signature: str | None = None

    @property
    def config(self) -> MqttConfig:
        return self._config

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, device_id: str, device: DeviceInfo | None = None) -> None:
        """Connect to the broker, set LWT, and publish availability=online."""
        self._device_id = device_id
        if self._client is None:
            self._client = self._client_factory(self._config)

        client = self._client
        if self._config.username:
            client.username_pw_set(self._config.username, self._config.password)
        if self._config.use_tls:
            client.tls_set()

        availability = self._config.availability_topic(device_id)
        client.will_set(availability, payload="offline", qos=self._config.qos, retain=True)
        client.connect(self._config.host, self._config.port, self._config.keepalive)
        client.loop_start()
        self._connected = True

        client.publish(availability, payload="online", qos=self._config.qos, retain=True)
        if self._config.discovery:
            self._publish_discovery(device_id, device)

    def publish_reading(self, reading: Reading) -> None:
        if not self._connected or self._client is None or self._device_id is None:
            return
        payload = json.dumps(_reading_payload(reading))
        self._client.publish(
            self._config.reading_topic(self._device_id),
            payload=payload,
            qos=self._config.qos,
            retain=self._config.retain,
        )

    def disconnect(self) -> None:
        if self._client is None:
            return
        try:
            if self._device_id is not None:
                self._client.publish(
                    self._config.availability_topic(self._device_id),
                    payload="offline",
                    qos=self._config.qos,
                    retain=True,
                )
            self._client.loop_stop()
            self._client.disconnect()
        finally:
            self._connected = False

    # -- Home Assistant discovery ------------------------------------------

    def _publish_discovery(self, device_id: str, device: DeviceInfo | None) -> None:
        assert self._client is not None
        node = _slug(device_id)
        state_topic = self._config.reading_topic(device_id)
        availability_topic = self._config.availability_topic(device_id)
        device_block = _device_block(device_id, device)

        for sensor in _discovery_sensors():
            object_id = f"{node}_{sensor['key']}"
            topic = f"{self._config.discovery_prefix}/sensor/{node}/{sensor['key']}/config"
            payload: dict[str, Any] = {
                "name": sensor["name"],
                "unique_id": object_id,
                "object_id": object_id,
                "state_topic": state_topic,
                "value_template": sensor["value_template"],
                "availability_topic": availability_topic,
                "payload_available": "online",
                "payload_not_available": "offline",
                "device": device_block,
            }
            if sensor.get("unit_template"):
                # The meter changes units at runtime, so unit is delivered via a
                # template rather than a static unit_of_measurement.
                payload["unit_of_measurement"] = sensor["unit_template"]
            if sensor.get("icon"):
                payload["icon"] = sensor["icon"]
            self._client.publish(
                topic,
                payload=json.dumps(payload),
                qos=self._config.qos,
                retain=True,
            )


def _discovery_sensors() -> list[dict[str, Any]]:
    return [
        {
            "key": "value",
            "name": "Reading Value",
            "value_template": "{{ value_json.value }}",
            "unit_template": "{{ value_json.unit }}",
            "icon": "mdi:gauge",
        },
        {
            "key": "unit",
            "name": "Reading Unit",
            "value_template": "{{ value_json.unit }}",
            "icon": "mdi:ruler",
        },
        {
            "key": "measurement_type",
            "name": "Measurement Type",
            "value_template": "{{ value_json.measurement_type }}",
            "icon": "mdi:sine-wave",
        },
        {
            "key": "display",
            "name": "Reading Display",
            "value_template": "{{ value_json.display_text }}",
            "icon": "mdi:format-text",
        },
    ]


def _device_block(device_id: str, device: DeviceInfo | None) -> dict[str, Any]:
    model = "Fluke Meter"
    name = f"Fluke {device_id}"
    if device is not None:
        model = device.model_name or model
        name = device.nickname or device.model_name or name
    return {
        "identifiers": [f"fluke_{_slug(device_id)}"],
        "name": name,
        "manufacturer": "Fluke (community)",
        "model": model,
    }


def _reading_payload(reading: Reading) -> dict[str, Any]:
    return {
        "timestamp": reading.timestamp_utc.isoformat() if reading.timestamp_utc else None,
        "value": reading.value,
        "unit": reading.unit,
        "measurement_type": reading.measurement_type.value,
        "status": reading.status.value,
        "display_text": reading.display_text,
        "mode": reading.mode,
        "device_id": reading.source_device_id,
    }


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", value.strip()).strip("_")
    return slug.lower() or "device"


def _build_paho_client(config: MqttConfig) -> MqttClientProtocol:
    try:
        import paho.mqtt.client as mqtt
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised without extra
        raise RuntimeError(
            "MQTT support requires the optional `paho-mqtt` package. "
            "Install with `pip install -e \".[mqtt]\"`."
        ) from exc
    try:  # paho-mqtt >= 2.0 requires an explicit callback API version
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=config.client_id)
    except (AttributeError, TypeError):  # pragma: no cover - paho < 2.0 fallback
        return mqtt.Client(client_id=config.client_id)
