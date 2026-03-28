from __future__ import annotations

import asyncio

from fluke_sdk.bootstrap import ensure_repo_paths

ensure_repo_paths()

from fluke_sdk import FlukeClient


async def main() -> int:
    client = FlukeClient()
    devices = await client.scan(timeout_s=5.0)
    for device in devices:
        print(f"{device.device_id} | {device.model_name} | {device.nickname or '-'}")
    if not devices:
        return 0

    await client.connect(devices[0].device_id)
    try:
        async for reading in client.stream_readings():
            print(reading.display_text)
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
