from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from tests.unit._helpers import PACKAGES  # noqa: F401 - ensures sys.path setup

from fluke_app.mqtt_publisher import MqttConfig, MqttPublisher
from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading

_BASE = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _reading(value: float = 121.3) -> Reading:
    return Reading(
        timestamp_utc=_BASE,
        value=value,
        unit="V",
        measurement_type=MeasurementType.VOLTAGE_AC,
        status=ReadingStatus.OK,
        display_text=f"{value} V",
        source_device_id="meter-1",
    )


class FakeMqttClient:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, int, bool]] = []
        self.will: tuple[str, str, int, bool] | None = None
        self.connected_to: tuple[str, int, int] | None = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False
        self.credentials: tuple[str | None, str | None] | None = None
        self.tls = False

    def username_pw_set(self, username, password=None):
        self.credentials = (username, password)

    def tls_set(self, *args, **kwargs):
        self.tls = True

    def will_set(self, topic, payload=None, qos=0, retain=False):
        self.will = (topic, payload, qos, retain)

    def connect(self, host, port=1883, keepalive=60):
        self.connected_to = (host, port, keepalive)

    def loop_start(self):
        self.loop_started = True

    def loop_stop(self):
        self.loop_stopped = True

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))

    def disconnect(self):
        self.disconnected = True

    def messages_for(self, topic: str) -> list[str]:
        return [payload for (t, payload, _q, _r) in self.published if t == topic]


class MqttPublisherTests(unittest.TestCase):
    def _publisher(self, **config_kwargs) -> tuple[MqttPublisher, FakeMqttClient]:
        client = FakeMqttClient()
        config = MqttConfig(base_topic="fluke", **config_kwargs)
        return MqttPublisher(config, client=client), client

    def test_connect_sets_lwt_and_online(self) -> None:
        publisher, client = self._publisher(discovery=False)
        publisher.connect("meter-1")
        self.assertEqual(client.connected_to, ("localhost", 1883, 60))
        self.assertTrue(client.loop_started)
        self.assertEqual(client.will, ("fluke/meter_1/availability", "offline", 0, True))
        online = client.messages_for("fluke/meter_1/availability")
        self.assertIn("online", online)

    def test_credentials_and_tls(self) -> None:
        publisher, client = self._publisher(
            discovery=False, username="user", password="secret", use_tls=True
        )
        publisher.connect("meter-1")
        self.assertEqual(client.credentials, ("user", "secret"))
        self.assertTrue(client.tls)

    def test_publish_reading_json(self) -> None:
        publisher, client = self._publisher(discovery=False)
        publisher.connect("meter-1")
        publisher.publish_reading(_reading(121.3))
        payloads = client.messages_for("fluke/meter_1/reading")
        self.assertEqual(len(payloads), 1)
        body = json.loads(payloads[0])
        self.assertEqual(body["value"], 121.3)
        self.assertEqual(body["unit"], "V")
        self.assertEqual(body["measurement_type"], "voltage_ac")
        self.assertEqual(body["device_id"], "meter-1")

    def test_publish_reading_before_connect_is_noop(self) -> None:
        publisher, client = self._publisher(discovery=False)
        publisher.publish_reading(_reading())
        self.assertEqual(client.published, [])

    def test_discovery_messages(self) -> None:
        device = DeviceInfo(
            device_id="meter-1",
            ble_address="AA:BB",
            model_name="Fluke 376 FC",
            profile_id="fluke_376fc",
            nickname="Bench Meter",
        )
        publisher, client = self._publisher(discovery=True)
        publisher.connect("meter-1", device=device)

        config_topic = "homeassistant/sensor/meter_1/value/config"
        configs = client.messages_for(config_topic)
        self.assertEqual(len(configs), 1)
        payload = json.loads(configs[0])
        self.assertEqual(payload["state_topic"], "fluke/meter_1/reading")
        self.assertEqual(payload["value_template"], "{{ value_json.value }}")
        self.assertEqual(payload["availability_topic"], "fluke/meter_1/availability")
        self.assertEqual(payload["device"]["identifiers"], ["fluke_meter_1"])
        self.assertEqual(payload["device"]["name"], "Bench Meter")
        self.assertEqual(payload["device"]["model"], "Fluke 376 FC")
        self.assertEqual(payload["device"]["manufacturer"], "Fluke (community)")

        # All four sensors published as retained config messages.
        for key in ("value", "unit", "measurement_type", "display"):
            topic = f"homeassistant/sensor/meter_1/{key}/config"
            msgs = [(t, p, q, r) for (t, p, q, r) in client.published if t == topic]
            self.assertEqual(len(msgs), 1, key)
            self.assertTrue(msgs[0][3], f"{key} config should be retained")

    def test_disconnect_publishes_offline(self) -> None:
        publisher, client = self._publisher(discovery=False)
        publisher.connect("meter-1")
        publisher.disconnect()
        offline = client.messages_for("fluke/meter_1/availability")
        self.assertIn("offline", offline)
        self.assertTrue(client.loop_stopped)
        self.assertTrue(client.disconnected)
        self.assertFalse(publisher.is_connected)

    def test_client_factory_used_when_no_client(self) -> None:
        created: list[MqttConfig] = []
        fake = FakeMqttClient()

        def factory(config: MqttConfig) -> FakeMqttClient:
            created.append(config)
            return fake

        config = MqttConfig(discovery=False)
        publisher = MqttPublisher(config, client_factory=factory)
        publisher.connect("meter-1")
        self.assertEqual(len(created), 1)
        self.assertTrue(fake.loop_started)

    def test_qos_and_retain_applied_to_readings(self) -> None:
        publisher, client = self._publisher(discovery=False, qos=1, retain=True)
        publisher.connect("meter-1")
        publisher.publish_reading(_reading())
        reading_msgs = [(t, p, q, r) for (t, p, q, r) in client.published if t.endswith("/reading")]
        self.assertEqual(reading_msgs[0][2], 1)
        self.assertTrue(reading_msgs[0][3])

    def test_topic_slugging(self) -> None:
        config = MqttConfig(base_topic="fluke")
        self.assertEqual(config.reading_topic("AA:BB:CC"), "fluke/aa_bb_cc/reading")
        self.assertEqual(config.availability_topic("Meter 1"), "fluke/meter_1/availability")


if __name__ == "__main__":
    unittest.main()
