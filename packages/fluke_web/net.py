from __future__ import annotations

import socket


def enumerate_lan_ips() -> list[str]:
    """Return a best-effort, de-duplicated list of the host's LAN IPv4 addresses.

    Ordering favors the address most likely to be reachable from a phone on the
    same network (the route the OS would use to reach the internet) first, then
    any other discovered private addresses, then loopback as a last resort.
    """
    addresses: list[str] = []

    primary = _primary_route_ip()
    if primary:
        addresses.append(primary)

    for candidate in _hostname_ips():
        if candidate not in addresses:
            addresses.append(candidate)

    # Loopback is always valid for the machine itself; keep it last so the
    # printed "primary" URL prefers a shareable address when one exists.
    if "127.0.0.1" not in addresses:
        addresses.append("127.0.0.1")

    return addresses


def _primary_route_ip() -> str | None:
    # Opening a UDP socket toward a public address does not send any packets but
    # lets the OS pick the source interface it would route through.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()
    if isinstance(ip, str) and ip and not ip.startswith("127."):
        return ip
    return None


def _hostname_ips() -> list[str]:
    found: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, family=socket.AF_INET):
            ip = info[4][0]
            if isinstance(ip, str) and ip and not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found


def build_urls(ips: list[str], port: int, token: str | None = None) -> list[str]:
    suffix = f"?token={token}" if token else ""
    return [f"http://{ip}:{port}/{suffix}" for ip in ips]
