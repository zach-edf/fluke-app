from __future__ import annotations

__all__ = ["FlukeClient", "ReadingStream"]


def __getattr__(name: str):
    if name == "FlukeClient":
        from fluke_sdk.client import FlukeClient

        return FlukeClient
    if name == "ReadingStream":
        from fluke_sdk.stream import ReadingStream

        return ReadingStream
    raise AttributeError(name)
