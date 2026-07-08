from __future__ import annotations

from fluke_app.device_manager import ConnectionAttemptStatus
from fluke_app.session_recorder import SessionRecorder

#: Marker labels inserted automatically so gaps are visible in replay/exports.
MARKER_CONNECTION_LOST = "connection_lost"
MARKER_CONNECTION_RESTORED = "connection_restored"


class SessionConnectionMarkers:
    """Bridge that inserts gap markers into the active recording session.

    Wire it to a :class:`DeviceManager` via
    ``manager.subscribe_connection_diagnostics(bridge.handle_status)``. When an
    established connection drops unexpectedly and the recorder still has an active
    session, a ``connection_lost`` marker is written; when the manager recovers,
    a ``connection_restored`` marker is written. Because the recorder keeps the
    same session across the drop, readings continue to append to the same
    ``session_id`` and the two markers bracket the visible gap.
    """

    def __init__(self, recorder: SessionRecorder, *, source: str = "auto") -> None:
        self._recorder = recorder
        self._source = source
        self._lost_open = False

    def handle_status(self, status: ConnectionAttemptStatus) -> None:
        if self._recorder.active_session() is None:
            return
        if status.phase == "recovery_waiting":
            self._mark_lost(status.message or "Connection lost.")
        elif status.phase == "recovered":
            self._mark_restored(status.message or "Connection restored.")

    def _mark_lost(self, note: str) -> None:
        if self._lost_open:
            return
        if self._add(note, MARKER_CONNECTION_LOST):
            self._lost_open = True

    def _mark_restored(self, note: str) -> None:
        if not self._lost_open:
            return
        self._add(note, MARKER_CONNECTION_RESTORED)
        self._lost_open = False

    def _add(self, note: str, label: str) -> bool:
        try:
            self._recorder.add_marker(note, label=label, source=self._source)
            return True
        except RuntimeError:
            # No active session or marker storage not configured; skip silently.
            return False
