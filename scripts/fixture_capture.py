from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"
for entry in (ROOT, PACKAGES):
    text = str(entry)
    if text not in sys.path:
        sys.path.insert(0, text)

from apps.cli.runtime import require_bleak_adapter
from fluke_plugins import build_profile_registry
from fluke_testing import capture_fixture


async def _main(args: argparse.Namespace) -> int:
    adapter = require_bleak_adapter()()
    fixture = await capture_fixture(
        adapter,
        build_profile_registry(),
        device_id=args.device,
        profile_id=args.profile,
        duration_s=args.duration,
        max_frames=args.count,
    )
    print(fixture.export_json(args.output))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture a raw BLE fixture JSON for a supported profile.")
    parser.add_argument("--device", required=True)
    parser.add_argument("--profile", default="fluke_376fc")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--count", type=int, default=0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
