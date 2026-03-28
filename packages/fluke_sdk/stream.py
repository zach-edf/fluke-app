from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator

from fluke_core.models.reading import Reading


@dataclass(slots=True)
class ReadingStream:
    """Async iterator wrapper for streaming readings out of the SDK."""

    iterator: AsyncIterator[Reading]

    def __aiter__(self) -> AsyncIterator[Reading]:
        return self.iterator
