"""LAN-only live web view for a Fluke meter's reading stream.

This package provides a small ``aiohttp`` server that subscribes to the live
reading stream and serves a self-contained mobile-first page, a WebSocket feed,
and a read-only JSON API. It is an optional extra (``.[web]``) so the base CLI
install stays lightweight.
"""

from fluke_web.net import build_urls, enumerate_lan_ips
from fluke_web.page import render_page
from fluke_web.qr import render_qr_ascii
from fluke_web.server import WebLiveServer
from fluke_web.state import LiveState

__all__ = [
    "LiveState",
    "WebLiveServer",
    "build_urls",
    "enumerate_lan_ips",
    "render_page",
    "render_qr_ascii",
]
