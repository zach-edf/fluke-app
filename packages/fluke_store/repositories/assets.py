from __future__ import annotations

from contextlib import nullcontext
import sqlite3
from datetime import datetime, timezone

from fluke_core.models.asset import Asset


class AssetRepository:
    def __init__(self, con: sqlite3.Connection, lock=None):
        self._con = con
        self._lock = lock or nullcontext()

    def create(self, asset: Asset) -> Asset:
        created_at = asset.created_at or datetime.now(timezone.utc)
        with self._lock:
            self._con.execute(
                """
                INSERT INTO assets (
                    asset_id, name, asset_type, location, notes, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    name=excluded.name,
                    asset_type=excluded.asset_type,
                    location=excluded.location,
                    notes=excluded.notes,
                    created_at=excluded.created_at
                """,
                (
                    asset.asset_id,
                    asset.name,
                    asset.asset_type,
                    asset.location,
                    asset.notes,
                    created_at.isoformat(),
                ),
            )
            self._con.commit()
        return Asset(
            asset_id=asset.asset_id,
            name=asset.name,
            asset_type=asset.asset_type,
            location=asset.location,
            notes=asset.notes,
            created_at=created_at,
        )

    def update(self, asset: Asset) -> Asset:
        return self.create(asset)

    def get(self, asset_id: str) -> Asset | None:
        with self._lock:
            row = self._con.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
            ).fetchone()
        if row is None:
            return None
        return _asset_from_row(row)

    def list_all(self, limit: int = 200) -> list[Asset]:
        with self._lock:
            rows = self._con.execute(
                """
                SELECT * FROM assets
                ORDER BY name COLLATE NOCASE ASC, created_at ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_asset_from_row(row) for row in rows]

    def delete(self, asset_id: str) -> None:
        with self._lock:
            # Detach any linked sessions / workflow runs so they remain assetless.
            self._con.execute(
                "UPDATE sessions SET asset_id = NULL WHERE asset_id = ?", (asset_id,)
            )
            self._con.execute(
                "UPDATE workflow_runs SET asset_id = NULL WHERE asset_id = ?", (asset_id,)
            )
            self._con.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))
            self._con.commit()


def _asset_from_row(row: sqlite3.Row) -> Asset:
    return Asset(
        asset_id=row["asset_id"],
        name=row["name"],
        asset_type=row["asset_type"] or "",
        location=row["location"] or "",
        notes=row["notes"] or "",
        created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else None,
    )
