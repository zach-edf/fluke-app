from __future__ import annotations

from typing import Any

from fluke_protocol.profiles.base import DeviceProfile


class ProfileRegistry:
    def __init__(self, profiles: list[DeviceProfile]):
        self._profiles = profiles

    def resolve(self, advertisement_name: str | None, metadata: dict[str, Any]) -> DeviceProfile | None:
        for profile in self._profiles:
            if profile.matches(advertisement_name, metadata):
                return profile
        return None

    def get(self, profile_id: str) -> DeviceProfile | None:
        for profile in self._profiles:
            if profile.profile_id == profile_id:
                return profile
        return None

    def default(self) -> DeviceProfile | None:
        if len(self._profiles) == 1:
            return self._profiles[0]
        return None
