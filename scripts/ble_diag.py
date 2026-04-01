"""
BLE diagnostic script — dumps raw bleak advertisement data.
Run with:  python scripts/ble_diag.py [--timeout 10]
"""
from __future__ import annotations

import asyncio
import argparse
import sys


async def main(timeout: float) -> None:
    try:
        from bleak import BleakScanner
    except ImportError:
        print("ERROR: bleak is not installed in this environment.", file=sys.stderr)
        sys.exit(1)

    import bleak
    try:
        from importlib.metadata import version as pkg_version
        bleak_ver = pkg_version("bleak")
    except Exception:
        bleak_ver = getattr(bleak, "__version__", "unknown")
    print(f"bleak version : {bleak_ver}")
    print(f"Python        : {sys.version}")
    print(f"Platform      : {sys.platform}")
    print(f"Scanning for {timeout}s ...\n")

    try:
        discovered = await BleakScanner.discover(timeout=timeout, return_adv=True)
    except TypeError:
        print("WARNING: this bleak version does not support return_adv=True — falling back.")
        devices = await BleakScanner.discover(timeout=timeout)
        for d in devices:
            print(f"  address : {d.address}")
            print(f"  name    : {d.name!r}")
            print(f"  rssi    : {getattr(d, 'rssi', 'n/a')}")
            print()
        return

    if not discovered:
        print("No devices found.")
        return

    for identifier, (device, adv) in discovered.items():
        print(f"{'─'*60}")
        print(f"  identifier       : {identifier}")
        print(f"  device.address   : {device.address!r}")
        print(f"  device.name      : {device.name!r}")
        print(f"  adv.local_name   : {adv.local_name!r}")
        print(f"  adv.rssi         : {adv.rssi}")
        print(f"  adv.service_uuids: {list(adv.service_uuids or [])}")
        mfr = dict(adv.manufacturer_data or {})
        print(f"  adv.mfr_data ids : {sorted(mfr.keys())}  (raw: {mfr})")
        print(f"  adv.service_data : {dict(adv.service_data or {})}")
        print(f"  adv.tx_power     : {adv.tx_power}")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Raw BLE advertisement dump")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    asyncio.run(main(args.timeout))
