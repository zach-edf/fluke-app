from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ROOT / "packages"

for path in (ROOT, PACKAGES):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)


def measurement_payload(primary: str, mode: str) -> bytes:
    display = primary.ljust(10)[:10].encode("ascii")
    mode_bytes = mode.ljust(5)[:5].encode("ascii")
    return b"\x00" + display + b"\x00" + mode_bytes


def utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)
