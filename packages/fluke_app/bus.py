from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable[[object], None]]] = {}

    def subscribe(self, event_type: type[T], handler: Callable[[T], None]) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event: object) -> None:
        for handler in self._handlers.get(type(event), []):
            handler(event)
