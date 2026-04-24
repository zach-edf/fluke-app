from __future__ import annotations

from typing import Any

from fluke_protocol.profiles.base import DeviceMatch, DeviceProfile


class ProfileRegistry:
    def __init__(self, profiles: list[DeviceProfile]):
        seen: set[str] = set()
        ordered: list[DeviceProfile] = []
        for profile in profiles:
            if profile.profile_id in seen:
                raise RuntimeError(f"Duplicate profile id {profile.profile_id!r}.")
            seen.add(profile.profile_id)
            ordered.append(profile)
        self._profiles = ordered

    def resolve(self, advertisement_name: str | None, metadata: dict[str, Any]) -> DeviceMatch | None:
        best_match: DeviceMatch | None = None
        for profile in self._profiles:
            match = profile.create_match(advertisement_name, metadata)
            if match is None:
                continue
            if best_match is None:
                best_match = match
                continue
            if match.score > best_match.score:
                best_match = match
                continue
            if match.score == best_match.score and self._break_tie(match, best_match):
                best_match = match
        return best_match

    def get(self, profile_id: str) -> DeviceProfile | None:
        for profile in self._profiles:
            if profile.profile_id == profile_id:
                return profile
        return None

    def default(self) -> DeviceProfile | None:
        if len(self._profiles) == 1:
            return self._profiles[0]
        return None

    def all(self) -> list[DeviceProfile]:
        return list(self._profiles)

    def _break_tie(self, candidate: DeviceMatch, incumbent: DeviceMatch) -> bool:
        candidate_services = _service_uuid_score(candidate.metadata)
        incumbent_services = _service_uuid_score(incumbent.metadata)
        if candidate_services != incumbent_services:
            return candidate_services > incumbent_services

        candidate_exact = _exact_model_match(candidate)
        incumbent_exact = _exact_model_match(incumbent)
        if candidate_exact != incumbent_exact:
            return candidate_exact

        candidate_hint = _device_hint_score(candidate.metadata, candidate.variant_id)
        incumbent_hint = _device_hint_score(incumbent.metadata, incumbent.variant_id)
        if candidate_hint != incumbent_hint:
            return candidate_hint > incumbent_hint

        return candidate.profile_id < incumbent.profile_id


def _service_uuid_score(metadata: dict[str, Any]) -> int:
    service_uuids = metadata.get("service_uuids")
    if not isinstance(service_uuids, list):
        return 0
    return len([item for item in service_uuids if isinstance(item, str) and item.strip()])


def _exact_model_match(match: DeviceMatch) -> bool:
    candidate_names = {
        (match.advertisement_name or "").lower().replace(" ", ""),
        str(match.metadata.get("advertisement_name") or "").lower().replace(" ", ""),
    }
    return match.variant_id.lower().replace("_", "") in candidate_names


def _device_hint_score(metadata: dict[str, Any], variant_id: str) -> int:
    hint_keys = ("device_id", "cnx_device_id", "model_number", "device_name", "advertisement_name")
    score = 0
    token = variant_id.lower().replace("_", "")
    for key in hint_keys:
        value = metadata.get(key)
        if isinstance(value, str) and token in value.lower().replace(" ", ""):
            score += 1
    return score
