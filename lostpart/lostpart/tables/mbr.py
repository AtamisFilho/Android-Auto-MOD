"""MBR parsing and building, including the extended boot record chain.

Layout (IBM PC / Microsoft partition table):

======  ==========================================================
Offset  Content
======  ==========================================================
0x000   Bootstrap code (446 bytes)
0x1BE   Four 16 byte partition entries
0x1FE   Boot signature ``55 AA``
======  ==========================================================

Each partition entry is::

    0x00  boot indicator (0x80 = active)
    0x01  start head
    0x02  start sector / cylinder high
    0x03  start cylinder
    0x04  partition type byte
    0x05  end head
    0x06  end sector / cylinder high
    0x07  end cylinder
    0x08  relative sector (start LBA, little endian)
    0x0C  number of sectors (little endian)
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, replace

from ..constants import (
    MBR_BOOT_SIGNATURE,
    MBR_LBA,
    MBR_MAX_PRIMARY,
    MBR_TYPE_EXTENDED,
    MBR_TYPE_EXTENDED_WIN,
    MBR_TYPE_LABELS,
)

__all__ = [
    "MbrPartitionEntry",
    "MbrSector",
    "parse_mbr",
    "build_mbr_sector",
    "parse_logical_partitions",
    "find_free_primary_slot",
    "lba_to_chs",
    "chs_to_lba",
    "PARTITION_ENTRY_SIZE",
    "PARTITION_TABLE_OFFSET",
]

PARTITION_ENTRY_SIZE = 16
PARTITION_TABLE_OFFSET = 0x1BE
BOOT_SIGNATURE_OFFSET = 0x1FE

#: Geometry used to convert LBA to CHS.  Legacy BIOS geometry.
_HEADS = 255
_SECTORS_PER_TRACK = 63
_CYLINDERS = 1024
_MAX_CHS_LBA = _HEADS * _SECTORS_PER_TRACK * _CYLINDERS


@dataclass(frozen=True)
class MbrPartitionEntry:
    """One 16 byte MBR partition entry."""

    index: int
    boot_indicator: int
    start_lba: int
    sector_count: int
    type_byte: int
    start_head: int = 0
    start_sector: int = 0
    start_cylinder: int = 0
    end_head: int = 0
    end_sector: int = 0
    end_cylinder: int = 0

    @property
    def is_empty(self) -> bool:
        """True when the entry carries no partition."""
        return self.type_byte == 0 and self.start_lba == 0 and self.sector_count == 0

    @property
    def is_extended(self) -> bool:
        """True when the entry points at an extended boot record."""
        return self.type_byte in (MBR_TYPE_EXTENDED, MBR_TYPE_EXTENDED_WIN)

    @property
    def is_active(self) -> bool:
        return self.boot_indicator == 0x80

    @property
    def end_lba(self) -> int:
        return self.start_lba + self.sector_count

    @property
    def label(self) -> str:
        return MBR_TYPE_LABELS.get(self.type_byte, f"Unknown (0x{self.type_byte:02X})")

    def to_bytes(self) -> bytes:
        """Serialise the entry back to its 16 byte on-disk form."""
        return struct.pack(
            "<BBBBBBBBII",
            self.boot_indicator,
            self.start_head,
            self.start_sector,
            self.start_cylinder,
            self.type_byte,
            self.end_head,
            self.end_sector,
            self.end_cylinder,
            self.start_lba,
            self.sector_count,
        )

    @classmethod
    def from_bytes(cls, data: bytes, index: int) -> "MbrPartitionEntry":
        (
            boot_indicator, start_head, start_sector, start_cylinder,
            type_byte, end_head, end_sector, end_cylinder, start_lba, sector_count,
        ) = struct.unpack("<BBBBBBBBII", data)
        return cls(
            index=index,
            boot_indicator=boot_indicator,
            start_lba=start_lba,
            sector_count=sector_count,
            type_byte=type_byte,
            start_head=start_head,
            start_sector=start_sector,
            start_cylinder=start_cylinder,
            end_head=end_head,
            end_sector=end_sector,
            end_cylinder=end_cylinder,
        )


@dataclass(frozen=True)
class MbrSector:
    """A parsed MBR sector."""

    entries: tuple[MbrPartitionEntry, ...]
    signature_valid: bool
    bootstrap: bytes = b""
    raw: bytes = b""

    @property
    def primary_entries(self) -> tuple[MbrPartitionEntry, ...]:
        return self.entries[:MBR_MAX_PRIMARY]

    def extended_entry(self) -> MbrPartitionEntry | None:
        """Return the primary entry that points at an extended container."""
        for entry in self.primary_entries:
            if entry.is_extended:
                return entry
        return None


def parse_mbr(data: bytes) -> MbrSector:
    """Parse an MBR sector.

    A sector whose boot signature is missing is still returned, with
    ``signature_valid`` set to ``False`` so callers can decide whether the
    sector is usable.
    """
    if len(data) < 512:
        return MbrSector(entries=(), signature_valid=False, raw=data)
    bootstrap = data[:PARTITION_TABLE_OFFSET]
    entries = []
    for i in range(MBR_MAX_PRIMARY):
        off = PARTITION_TABLE_OFFSET + i * PARTITION_ENTRY_SIZE
        entries.append(MbrPartitionEntry.from_bytes(data[off:off + PARTITION_ENTRY_SIZE], i))
    signature_valid = data[BOOT_SIGNATURE_OFFSET:BOOT_SIGNATURE_OFFSET + 2] == MBR_BOOT_SIGNATURE
    return MbrSector(
        entries=tuple(entries),
        signature_valid=signature_valid,
        bootstrap=bootstrap,
        raw=bytes(data[:512]),
    )


def lba_to_chs(lba: int, heads: int = _HEADS, spt: int = _SECTORS_PER_TRACK) -> tuple[int, int, int]:
    """Convert an LBA to a CHS triple.

    The triple is returned in the form the MBR stores it: the sector byte
    carries the two high bits of the cylinder, the cylinder byte the low
    eight.  Values beyond the legacy 1024x255x63 geometry cannot be
    represented and are reported as ``0xFE 0xFF 0xFF``, the conventional
    "use LBA" marker.
    """
    if lba >= _MAX_CHS_LBA:
        return (0xFE, 0xFF, 0xFF)
    cylinder = lba // (heads * spt)
    remainder = lba % (heads * spt)
    head = remainder // spt
    sector = remainder % spt + 1
    sector_byte = ((cylinder >> 8) << 6) | (sector & 0x3F)
    return (head, sector_byte, cylinder & 0xFF)


def chs_to_lba(head: int, sector: int, cylinder: int,
              heads: int = _HEADS, spt: int = _SECTORS_PER_TRACK) -> int:
    """Convert a CHS triple, as stored in an MBR entry, back to an LBA."""
    full_cylinder = ((sector & 0xC0) << 2) | (cylinder & 0xFF)
    return (full_cylinder * heads + head) * spt + ((sector & 0x3F) - 1)


def build_mbr_sector(
    entries: list[MbrPartitionEntry],
    bootstrap: bytes = b"\x00" * PARTITION_TABLE_OFFSET,
    signature: bool = True,
) -> bytes:
    """Build a complete MBR sector from the given primary entries.

    ``entries`` may hold fewer than four entries; the remaining slots are
    filled with empty entries.  The boot signature is only written when
    ``signature`` is true, which matters for tools that deliberately keep an
    invalid MBR in place.
    """
    if len(bootstrap) > PARTITION_TABLE_OFFSET:
        bootstrap = bootstrap[:PARTITION_TABLE_OFFSET]
    bootstrap = bootstrap.ljust(PARTITION_TABLE_OFFSET, b"\x00")
    out = bytearray(bootstrap)
    for i in range(MBR_MAX_PRIMARY):
        if i < len(entries):
            out += entries[i].to_bytes()
        else:
            out += b"\x00" * PARTITION_ENTRY_SIZE
    out += b"\x55\xaa" if signature else b"\x00\x00"
    return bytes(out)


def parse_logical_partitions(
    read_sector: "callable",
    extended_entry: MbrPartitionEntry,
    max_entries: int = 60,
) -> list[MbrPartitionEntry]:
    """Walk the extended boot record chain of an extended partition.

    ``read_sector`` must be a callable taking an LBA and returning the raw
    sector bytes.  The returned entries use the same layout as primary
    entries; their ``index`` continues after the primary slots.
    """
    result: list[MbrPartitionEntry] = []
    next_ebr = extended_entry.start_lba
    seen: set[int] = set()
    index = MBR_MAX_PRIMARY

    while next_ebr and len(result) < max_entries:
        if next_ebr in seen:
            break
        seen.add(next_ebr)
        try:
            raw = read_sector(next_ebr)
        except Exception:
            break
        if len(raw) < 512:
            break
        ebr = parse_mbr(raw)
        if not ebr.signature_valid:
            break
        logical = ebr.entries[0]
        if logical.is_empty:
            break
        result.append(replace(logical, index=index))
        index += 1
        following = ebr.entries[1]
        if following.is_empty:
            break
        next_ebr = following.start_lba

    return result


def find_free_primary_slot(entries: tuple[MbrPartitionEntry, ...]) -> int | None:
    """Return the index of the first unused primary slot, or ``None``."""
    for entry in entries[:MBR_MAX_PRIMARY]:
        if entry.is_empty:
            return entry.index
    return None
