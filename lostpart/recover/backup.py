"""Backup and restore of partition table structures.

Before any write the tool copies the structures it is about to modify into a
self contained JSON file: the MBR sector, every extended boot record, and --
on a GPT disk -- the primary header, both entry arrays and the backup header.

The file is plain JSON with base64 payloads so it can be inspected and
restored with standard tools.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..device import RawDevice
from ..tables.table import TABLE_TYPE_GPT, PartitionTable

__all__ = ["TableBackup", "create_backup", "restore_backup", "load_backup", "BACKUP_VERSION"]

BACKUP_VERSION = 1


@dataclass
class TableBackup:
    """A saved copy of the partition table structures of a disk."""

    path: Path
    kind: str
    device_id: str
    sector_size: int
    total_sectors: int
    created: str
    chunks: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "version": BACKUP_VERSION,
            "kind": self.kind,
            "device_id": self.device_id,
            "sector_size": self.sector_size,
            "total_sectors": self.total_sectors,
            "created": self.created,
            "chunks": self.chunks,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object], path: Path) -> "TableBackup":
        return cls(
            path=path,
            kind=str(data.get("kind", "")),
            device_id=str(data.get("device_id", "")),
            sector_size=int(data.get("sector_size", 512)),
            total_sectors=int(data.get("total_sectors", 0)),
            created=str(data.get("created", "")),
            chunks=list(data.get("chunks", [])),  # type: ignore[arg-type]
        )


def _capture(device: RawDevice, start_lba: int, count: int) -> dict[str, object]:
    data = device.read_at(start_lba * device.sector_size, count * device.sector_size)
    return {
        "start_lba": start_lba,
        "count": count,
        "data": base64.b64encode(data).decode("ascii"),
    }


def create_backup(
    device: RawDevice,
    table: PartitionTable,
    path: str | Path,
    device_id: str = "",
) -> TableBackup:
    """Capture the partition table structures of a disk into a backup file."""
    sector_size = device.sector_size or 512
    chunks: list[dict[str, object]] = [_capture(device, 0, 1)]

    if table.kind == TABLE_TYPE_GPT and table.gpt_header is not None:
        header = table.gpt_header
        entry_count = header.partition_entry_count
        entry_size = header.partition_entry_size
        array_sectors = (entry_count * entry_size + sector_size - 1) // sector_size
        chunks.append(_capture(device, header.partition_entry_lba, array_sectors))
        backup_entry_lba = header.backup_lba - array_sectors + 1
        chunks.append(_capture(device, backup_entry_lba, array_sectors))
        chunks.append(_capture(device, header.backup_lba, 1))
    elif table.mbr is not None:
        # Capture every extended boot record of the chain.
        from ..tables.mbr import parse_logical_partitions

        extended = table.mbr.extended_entry()
        if extended is not None:
            def read_sector(lba: int) -> bytes:
                return device.read_at(lba * sector_size, sector_size)

            logical = parse_logical_partitions(read_sector, extended)
            for entry in logical:
                # The EBR precedes the logical partition it describes.
                chunks.append(_capture(device, max(0, entry.start_lba - 1), 1))

    backup = TableBackup(
        path=Path(path),
        kind=table.kind,
        device_id=device_id,
        sector_size=sector_size,
        total_sectors=device.total_sectors,
        created=time.strftime("%Y-%m-%dT%H:%M:%S"),
        chunks=chunks,
    )
    backup.path.write_text(json.dumps(backup.to_dict(), indent=1), encoding="utf-8")
    return backup


def load_backup(path: str | Path) -> TableBackup:
    """Read a backup file."""
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    return TableBackup.from_dict(data, path)


def restore_backup(device: RawDevice, backup: TableBackup) -> int:
    """Write a backup back to the disk.  Returns the number of bytes written."""
    sector_size = device.sector_size or 512
    written = 0
    for chunk in backup.chunks:
        start_lba = int(chunk["start_lba"])
        count = int(chunk["count"])
        payload = base64.b64decode(str(chunk["data"]))
        device.write_at(start_lba * sector_size, payload)
        written += len(payload)
    return written
