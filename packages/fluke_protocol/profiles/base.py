from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fluke_core.models.reading import Reading


@dataclass(frozen=True, slots=True)
class DeviceServiceSet:
    live_reading_service: object | None = None
    logging_service: object | None = None
    device_memory_service: object | None = None
    settings_service: object | None = None
    family_view_adapter: object | None = None


@dataclass(frozen=True, slots=True)
class DeviceConnectionContext:
    device_id: str
    profile_id: str
    family_id: str
    variant_id: str
    display_name: str
    model_hint: str
    advertisement_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DeviceMatch:
    profile_id: str
    family_id: str
    variant_id: str
    score: float
    display_name: str
    model_hint: str
    capabilities: tuple[str, ...]
    advertisement_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_connection_context(self, *, device_id: str) -> DeviceConnectionContext:
        return DeviceConnectionContext(
            device_id=device_id,
            profile_id=self.profile_id,
            family_id=self.family_id,
            variant_id=self.variant_id,
            display_name=self.display_name,
            model_hint=self.model_hint,
            advertisement_name=self.advertisement_name,
            metadata=dict(self.metadata),
        )


class DeviceFamilyRuntime(ABC):
    @abstractmethod
    def family_id(self) -> str:
        ...

    @abstractmethod
    def variant_id(self) -> str:
        ...

    @abstractmethod
    def capabilities(self) -> tuple[str, ...]:
        ...

    @abstractmethod
    def notification_subscriptions(self) -> list[str]:
        ...

    def initialize(self, connection_ctx: DeviceConnectionContext) -> None:
        del connection_ctx

    @abstractmethod
    def parse_notification(
        self,
        characteristic_uuid: str,
        payload: bytes,
        device_id: str,
        observed_at: datetime | None = None,
    ) -> list[Reading]:
        ...

    def services(self) -> DeviceServiceSet:
        return DeviceServiceSet()

    def reset_device(self, device_id: str) -> None:
        del device_id


class _LegacyProfileRuntime(DeviceFamilyRuntime):
    def __init__(self, profile: "DeviceProfile", match: DeviceMatch) -> None:
        self._profile = profile
        self._match = match

    def family_id(self) -> str:
        return self._match.family_id

    def variant_id(self) -> str:
        return self._match.variant_id

    def capabilities(self) -> tuple[str, ...]:
        return tuple(self._match.capabilities)

    def notification_subscriptions(self) -> list[str]:
        return self._profile.notification_characteristics()

    def parse_notification(
        self,
        characteristic_uuid: str,
        payload: bytes,
        device_id: str,
        observed_at: datetime | None = None,
    ) -> list[Reading]:
        return self._profile.parse_notification(
            characteristic_uuid=characteristic_uuid,
            payload=payload,
            device_id=device_id,
            observed_at=observed_at,
        )

    def reset_device(self, device_id: str) -> None:
        self._profile.reset_device(device_id)


class DeviceProfile(ABC):
    profile_id: str
    model_name: str

    def family_id(self) -> str:
        return self.profile_id

    def variant_id(self) -> str:
        return self.profile_id

    def display_name(self) -> str:
        return self.model_name

    @abstractmethod
    def matches(self, advertisement_name: str | None, metadata: dict[str, Any]) -> bool:
        ...

    def match_score(self, advertisement_name: str | None, metadata: dict[str, Any]) -> float:
        return 100.0 if self.matches(advertisement_name, metadata) else 0.0

    def create_match(self, advertisement_name: str | None, metadata: dict[str, Any]) -> DeviceMatch | None:
        score = self.match_score(advertisement_name, metadata)
        if score <= 0:
            return None
        return DeviceMatch(
            profile_id=self.profile_id,
            family_id=self.family_id(),
            variant_id=self.variant_id(),
            score=score,
            display_name=self.display_name(),
            model_hint=self.model_name,
            capabilities=tuple(self.capabilities()),
            advertisement_name=advertisement_name,
            metadata=dict(metadata),
        )

    @abstractmethod
    def capabilities(self) -> list[str]:
        ...

    @abstractmethod
    def notification_characteristics(self) -> list[str]:
        ...

    @abstractmethod
    def parse_notification(
        self,
        characteristic_uuid: str,
        payload: bytes,
        device_id: str,
        observed_at: datetime | None = None,
    ) -> list[Reading]:
        ...

    def reset_device(self, device_id: str) -> None:
        del device_id

    def create_runtime(self, match: DeviceMatch) -> DeviceFamilyRuntime:
        return _LegacyProfileRuntime(self, match)
