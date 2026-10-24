"""Resumable scan checkpoints backed by SQLite.

A full scan of a multi terabyte disk takes a long time.  The checkpoint keeps
track of what has been found so far and of the sector the scan reached, so an
interrupted scan can be continued instead of restarted.

The schema deliberately mirrors the classic checkpoint table used by
partition managers: a scan session with its start timestamp, the JSON
serialised list of found partitions, a status and the list of sectors holding
a backup boot record.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from .model import LostPartitionCandidate

logger = logging.getLogger(__name__)

__all__ = ["ScanCheckpoint", "CheckpointStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    scan_start_timestamp TEXT NOT NULL,
    lost_partitions_json TEXT NOT NULL,
    status TEXT NOT NULL,
    backup_dbr_sectors_json TEXT NOT NULL DEFAULT '[]',
    mode TEXT NOT NULL DEFAULT 'full',
    last_sector INTEGER NOT NULL DEFAULT 0,
    regions_json TEXT NOT NULL DEFAULT '[]'
);
"""

STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_CANCELLED = "cancelled"


@dataclass
class CheckpointStore:
    """A single checkpoint session."""

    id: int
    device_id: str
    mode: str
    status: str
    last_sector: int
    candidates: list[LostPartitionCandidate]

    @property
    def finished(self) -> bool:
        return self.status in (STATUS_DONE, STATUS_CANCELLED)


class ScanCheckpoint:
    """SQLite store for scan checkpoints."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- lifecycle -------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ScanCheckpoint":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def start(
        self,
        device_id: str,
        mode: str = "full",
        regions: list[dict[str, int]] | None = None,
    ) -> int:
        """Create a new checkpoint session and return its id."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        cursor = self._conn.execute(
            "INSERT INTO checkpoints (device_id, scan_start_timestamp, "
            "lost_partitions_json, status, backup_dbr_sectors_json, mode, "
            "last_sector, regions_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (device_id, now, "[]", STATUS_RUNNING, "[]", mode, 0,
             json.dumps(regions or [])),
        )
        self._conn.commit()
        return int(cursor.lastrowid or 0)

    def update(self, checkpoint_id: int, **fields: object) -> None:
        """Update arbitrary columns of a checkpoint."""
        if not fields:
            return
        columns = ", ".join(f"{name} = ?" for name in fields)
        self._conn.execute(
            f"UPDATE checkpoints SET {columns} WHERE id = ?",
            (*fields.values(), checkpoint_id),
        )
        self._conn.commit()

    def set_progress(self, checkpoint_id: int, last_sector: int) -> None:
        """Record the sector the scan has reached."""
        self.update(checkpoint_id, last_sector=int(last_sector))

    def add_candidate(self, checkpoint_id: int, candidate: LostPartitionCandidate) -> None:
        """Append a found partition to the checkpoint."""
        current = self._conn.execute(
            "SELECT lost_partitions_json FROM checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        items = json.loads(current["lost_partitions_json"]) if current else []
        items.append(candidate.to_dict())
        self.update(checkpoint_id, lost_partitions_json=json.dumps(items))

    def set_status(self, checkpoint_id: int, status: str) -> None:
        self.update(checkpoint_id, status=status)

    # -- retrieval --------------------------------------------------------
    def load(self, checkpoint_id: int) -> CheckpointStore | None:
        row = self._conn.execute(
            "SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)
        ).fetchone()
        if row is None:
            return None
        return CheckpointStore(
            id=int(row["id"]),
            device_id=row["device_id"],
            mode=row["mode"],
            status=row["status"],
            last_sector=int(row["last_sector"]),
            candidates=[_candidate_from_dict(item) for item in json.loads(row["lost_partitions_json"])],
        )

    def latest(self, device_id: str | None = None) -> CheckpointStore | None:
        """Return the most recent checkpoint, optionally filtered by device."""
        if device_id:
            row = self._conn.execute(
                "SELECT id FROM checkpoints WHERE device_id = ? ORDER BY id DESC LIMIT 1",
                (device_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT id FROM checkpoints ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self.load(int(row["id"]))

    def list_checkpoints(self) -> list[sqlite3.Row]:
        return list(
            self._conn.execute(
                "SELECT id, device_id, scan_start_timestamp, status, mode, last_sector "
                "FROM checkpoints ORDER BY id DESC"
            )
        )


def _candidate_from_dict(data: dict) -> LostPartitionCandidate:
    return LostPartitionCandidate(
        start_sector=int(data.get("start_sector", 0)),
        sector_count=int(data.get("sector_count", 0)),
        fs_type=str(data.get("fs_type", "")),
        label=str(data.get("label", "")),
        confidence=float(data.get("confidence", 0.0)),
        source=str(data.get("source", "")),
        evidence=tuple(data.get("evidence", ())),
        details=dict(data.get("details", {})),
        volume_name=str(data.get("volume_name", "")),
    )
