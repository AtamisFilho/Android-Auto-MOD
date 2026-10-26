"""Unified view over the MBR and GPT partition tables of a disk."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..constants import GPT_ENTRY_SIZE, GPT_HEADER_LBA, GPT_TYPE_LABELS
from ..device import RawDevice
from ..errors import PartitionTableError
from ..i18n import t
from .gpt import (
    GptEntry,
    GptHeader,
    MAX_PARTITION_ENTRIES,
    MAX_PARTITION_ENTRY_SIZE,
    build_protective_mbr,
    bytes_to_guid,
    parse_gpt_entries,
    parse_gpt_header,
    verify_gpt_header_crc,
)
from .mbr import MbrPartitionEntry, MbrSector, parse_logical_partitions, parse_mbr

logger = logging.getLogger(__name__)

__all__ = [
    "PartitionEntry",
    "PartitionTable",
    "detect_table_type",
    "load_partition_table",
    "TABLE_TYPE_MBR",
    "TABLE_TYPE_GPT",
    "TABLE_TYPE_NONE",
]

TABLE_TYPE_MBR = "mbr"
TABLE_TYPE_GPT = "gpt"
TABLE_TYPE_NONE = "none"


@dataclass(frozen=True)
class PartitionEntry:
    """A partition as seen by the rest of the tool."""

    index: int
    start_lba: int
    sector_count: int
    label: str
    type_code: str
    bootable: bool = False
    is_extended: bool = False
    is_logical: bool = False
    attributes: int = 0
    unique_guid: str | None = None
    raw_type_byte: int | None = None

    @property
    def end_lba(self) -> int:
        """First LBA after the partition."""
        return self.start_lba + self.sector_count

    @property
    def is_empty(self) -> bool:
        # A broken entry can carry a negative length; it describes nothing.
        return self.sector_count <= 0


@dataclass
class PartitionTable:
    """A parsed partition table."""

    kind: str
    entries: list[PartitionEntry] = field(default_factory=list)
    sector_size: int = 512
    total_sectors: int = 0
    mbr: MbrSector | None = None
    gpt_header: GptHeader | None = None
    gpt_entries: list[GptEntry] = field(default_factory=list)
    header_crc_valid: bool | None = None
    entry_array_crc_valid: bool | None = None

    @property
    def occupied(self) -> list[PartitionEntry]:
        """Entries that actually describe a partition."""
        return [e for e in self.entries if not e.is_empty]

    def sorted_by_start(self) -> list[PartitionEntry]:
        return sorted(self.occupied, key=lambda e: e.start_lba)


def detect_table_type(device: RawDevice) -> str:
    """Detect whether the disk carries an MBR, a GPT or nothing usable.

    The order matters: a GPT disk still has a protective MBR in LBA 0, so the
    GPT header is examined first.
    """
    sector_size = device.sector_size or 512
    try:
        header = device.read_at(GPT_HEADER_LBA * sector_size, sector_size)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("cannot read LBA %d: %s", GPT_HEADER_LBA, exc)
        header = b""
    gpt = parse_gpt_header(header)
    if gpt is not None and gpt.is_valid:
        return TABLE_TYPE_GPT

    try:
        mbr_sector = device.read_at(0, sector_size)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("cannot read LBA 0: %s", exc)
        mbr_sector = b""
    mbr = parse_mbr(mbr_sector)
    if mbr.signature_valid:
        return TABLE_TYPE_MBR
    if gpt is not None:
        # A GPT header with a damaged body is still closer to GPT than MBR.
        return TABLE_TYPE_GPT
    return TABLE_TYPE_NONE


def _mbr_to_entries(mbr: MbrSector, device: RawDevice, sector_size: int) -> list[PartitionEntry]:
    entries: list[PartitionEntry] = []
    for primary in mbr.primary_entries:
        if primary.is_empty:
            continue
        entries.append(
            PartitionEntry(
                index=primary.index,
                start_lba=primary.start_lba,
                sector_count=primary.sector_count,
                label=primary.label,
                type_code=f"0x{primary.type_byte:02X}",
                bootable=primary.is_active,
                is_extended=primary.is_extended,
                is_logical=False,
                raw_type_byte=primary.type_byte,
            )
        )

    extended = mbr.extended_entry()
    if extended is not None:
        def read_sector(lba: int) -> bytes:
            return device.read_at(lba * sector_size, sector_size)

        for logical in parse_logical_partitions(read_sector, extended):
            entries.append(
                PartitionEntry(
                    index=logical.index,
                    start_lba=logical.start_lba,
                    sector_count=logical.sector_count,
                    label=logical.label,
                    type_code=f"0x{logical.type_byte:02X}",
                    bootable=False,
                    is_extended=False,
                    is_logical=True,
                    raw_type_byte=logical.type_byte,
                )
            )
    return entries


def _gpt_to_entries(entries: list[GptEntry]) -> list[PartitionEntry]:
    out: list[PartitionEntry] = []
    for entry in entries:
        if entry.is_empty:
            continue
        out.append(
            PartitionEntry(
                index=entry.index,
                start_lba=entry.first_lba,
                sector_count=entry.sector_count,
                label=GPT_TYPE_LABELS.get(entry.type_guid, entry.name or entry.type_guid),
                type_code=entry.type_guid,
                bootable=bool(entry.attributes & (1 << 2)),
                unique_guid=entry.unique_guid,
                attributes=entry.attributes,
            )
        )
    return out


def load_partition_table(device: RawDevice) -> PartitionTable | None:
    """Read and parse the partition table of a device.

    Returns ``None`` when the device carries no recognisable partition table.
    """
    sector_size = device.sector_size or 512
    total_sectors = device.total_sectors
    kind = detect_table_type(device)

    if kind == TABLE_TYPE_GPT:
        header_bytes = device.read_at(GPT_HEADER_LBA * sector_size, sector_size)
        header = parse_gpt_header(header_bytes)
        if header is None:
            return None
        # The entry count and the entry size come from the disk and cannot
        # be trusted: a corrupt header would otherwise ask for an unbounded
        # read before anything is validated.
        if not (0 < header.partition_entry_count <= MAX_PARTITION_ENTRIES):
            raise PartitionTableError(t("error.gpt_entry_count",
                                         count=header.partition_entry_count))
        if not (GPT_ENTRY_SIZE <= header.partition_entry_size <= MAX_PARTITION_ENTRY_SIZE):
            raise PartitionTableError(t("error.gpt_entry_size",
                                         size=header.partition_entry_size))
        array_bytes = device.read_at(
            header.partition_entry_lba * sector_size,
            header.partition_entry_count * header.partition_entry_size,
        )
        entries = parse_gpt_entries(
            array_bytes, header.partition_entry_count, header.partition_entry_size
        )
        from .gpt import crc32

        expected = crc32(array_bytes[: header.partition_entry_count * header.partition_entry_size])
        return PartitionTable(
            kind=TABLE_TYPE_GPT,
            entries=_gpt_to_entries(entries),
            sector_size=sector_size,
            total_sectors=total_sectors,
            gpt_header=header,
            gpt_entries=entries,
            header_crc_valid=verify_gpt_header_crc(header_bytes),
            entry_array_crc_valid=expected == header.partition_entry_array_crc32,
        )

    if kind == TABLE_TYPE_MBR:
        mbr_sector = parse_mbr(device.read_at(0, sector_size))
        return PartitionTable(
            kind=TABLE_TYPE_MBR,
            entries=_mbr_to_entries(mbr_sector, device, sector_size),
            sector_size=sector_size,
            total_sectors=total_sectors,
            mbr=mbr_sector,
        )

    return None


def read_gpt_backup(device: RawDevice, header: GptHeader) -> tuple[bytes, bytes] | None:
    """Read the backup GPT header and entry array.

    The backup entry array sits immediately before the backup header.  Returns
    ``(header_bytes, entry_array_bytes)`` or ``None`` when the backup cannot
    be read or does not carry the expected signature.
    """
    sector_size = device.sector_size or 512
    if not (0 < header.partition_entry_count <= MAX_PARTITION_ENTRIES):
        raise PartitionTableError(t("error.gpt_entry_count",
                                     count=header.partition_entry_count))
    if not (GPT_ENTRY_SIZE <= header.partition_entry_size <= MAX_PARTITION_ENTRY_SIZE):
        raise PartitionTableError(t("error.gpt_entry_size",
                                     size=header.partition_entry_size))
    array_bytes_len = header.partition_entry_count * header.partition_entry_size
    array_sectors = (array_bytes_len + sector_size - 1) // sector_size
    # The backup array sits in the sectors immediately before the backup
    # header, so it starts at ``backup_lba - array_sectors``.  Starting one
    # sector later would put its last sector on top of the header.
    backup_entry_lba = header.backup_lba - array_sectors
    try:
        header_bytes = device.read_at(header.backup_lba * sector_size, sector_size)
        if header_bytes[:8] != b"EFI PART":
            return None
        array_bytes = device.read_at(backup_entry_lba * sector_size, array_bytes_len)
    except Exception:  # pragma: no cover - defensive
        return None
    return header_bytes, array_bytes
