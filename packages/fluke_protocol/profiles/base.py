from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from fluke_core.models.reading import Reading


class DeviceProfile(ABC):
    profile_id: str
    model_name: str

    @abstractmethod
    def matches(self, advertisement_name: str | None, metadata: dict[str, Any]) -> bool:
        ...

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
