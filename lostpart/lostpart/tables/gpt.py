"""GPT parsing, building and integrity verification.

A GUID partition table on an EFI system is laid out as::

    LBA 0                protective MBR
    LBA 1                primary GPT header
    LBA 2 .. 2+n-1       primary partition entry array
    ... disk data ...
    last LBA - n .. -1   backup partition entry array
    last LBA             backup GPT header

The GPT header is 92 bytes long (512 byte sector, remainder reserved) and is
protected by a CRC32 over the header with the CRC field zeroed.  The entry
array is protected by a second CRC32.

Reference: UEFI Specification 2.10, section 5.
"""

from __future__ import annotations

import struct
import uuid
import zlib
from dataclasses import dataclass

from ..constants import (
    GPT_ENTRY_SIZE,
    GPT_HEADER_LBA,
    GPT_SIGNATURE,
    GPT_TYPE_EMPTY,
    MBR_BOOT_SIGNATURE,
    MBR_TYPE_GPT_PROTECTIVE,
)

__all__ = [
    "GptHeader",
    "GptEntry",
    "parse_gpt_header",
    "parse_gpt_entries",
    "build_gpt_header",
    "build_gpt_entry",
    "build_protective_mbr",
    "crc32",
    "guid_to_bytes",
    "bytes_to_guid",
    "GPT_HEADER_SIZE",
    "MAX_PARTITION_ENTRIES",
    "MAX_PARTITION_ENTRY_SIZE",
]

GPT_HEADER_SIZE = 92
GPT_HEADER_STRUCT = "<8sIIIIQQQQ16sQIII"

#: Upper bound on the number of partition entries a GPT may declare.
#: UEFI 2.10 does not fix a number, but the layout has to fit between the
#: header and the first usable LBA, and every real implementation uses 128.
#: The bound keeps a corrupt header from asking for an unbounded read.
MAX_PARTITION_ENTRIES = 4096

#: Upper bound on the size of one partition entry.  The entry itself is 128
#: bytes; Linux also accepts 4 KiB and 16 KiB entries.
MAX_PARTITION_ENTRY_SIZE = 4096


def crc32(data: bytes) -> int:
    """CRC32 (IEEE 802.3, reflected, polynomial 0xEDB88320)."""
    return zlib.crc32(data) & 0xFFFFFFFF


def guid_to_bytes(text: str) -> bytes:
    """Encode a GUID string in the mixed endian form used on disk."""
    return uuid.UUID(text).bytes_le


def bytes_to_guid(data: bytes) -> str:
    """Decode a 16 byte on-disk GUID into its canonical braced string form."""
    return "{" + str(uuid.UUID(bytes_le=data)).upper() + "}"


@dataclass(frozen=True)
class GptEntry:
    """One GPT partition entry."""

    index: int
    type_guid: str
    unique_guid: str
    first_lba: int
    last_lba: int
    attributes: int
    name: str

    @property
    def is_empty(self) -> bool:
        return self.type_guid.upper() == GPT_TYPE_EMPTY

    @property
    def sector_count(self) -> int:
        if self.is_empty:
            return 0
        # A corrupt entry can declare a last LBA before its first one; the
        # length must never be negative.
        return max(0, self.last_lba - self.first_lba + 1)

    @property
    def end_lba(self) -> int:
        """First LBA *after* the partition."""
        return self.last_lba + 1

    def to_bytes(self) -> bytes:
        name_bytes = self.name.encode("utf-16-le")[:70]
        name_bytes = name_bytes.ljust(72, b"\x00")
        return (
            guid_to_bytes(self.type_guid)
            + guid_to_bytes(self.unique_guid)
            + struct.pack("<QQQ", self.first_lba, self.last_lba, self.attributes)
            + name_bytes
        )

    @classmethod
    def from_bytes(cls, data: bytes, index: int) -> "GptEntry":
        type_guid = bytes_to_guid(data[0x00:0x10])
        unique_guid = bytes_to_guid(data[0x10:0x20])
        first_lba, last_lba, attributes = struct.unpack_from("<QQQ", data, 0x20)
        raw_name = data[0x38:0x38 + 72]
        name = raw_name.decode("utf-16-le", "ignore").rstrip("\x00")
        return cls(
            index=index,
            type_guid=type_guid,
            unique_guid=unique_guid,
            first_lba=first_lba,
            last_lba=last_lba,
            attributes=attributes,
            name=name,
        )


@dataclass(frozen=True)
class GptHeader:
    """A parsed GPT header."""

    revision: int
    header_size: int
    crc32: int
    current_lba: int
    backup_lba: int
    first_usable_lba: int
    last_usable_lba: int
    disk_guid: str
    partition_entry_lba: int
    partition_entry_count: int
    partition_entry_size: int
    partition_entry_array_crc32: int
    raw: bytes = b""

    @property
    def is_valid(self) -> bool:
        return (
            0 < self.partition_entry_count <= MAX_PARTITION_ENTRIES
            and GPT_ENTRY_SIZE <= self.partition_entry_size <= MAX_PARTITION_ENTRY_SIZE
            and self.last_usable_lba >= self.first_usable_lba
        )


def parse_gpt_header(data: bytes) -> GptHeader | None:
    """Parse a GPT header sector.  Returns ``None`` when the signature is wrong."""
    if len(data) < GPT_HEADER_SIZE:
        return None
    if data[0:8] != GPT_SIGNATURE:
        return None
    (
        _sig, revision, header_size, header_crc, _reserved,
        current_lba, backup_lba, first_usable, last_usable,
        disk_guid_raw, entry_lba, entry_count, entry_size, entry_crc,
    ) = struct.unpack_from(GPT_HEADER_STRUCT, data, 0)
    return GptHeader(
        revision=revision,
        header_size=header_size,
        crc32=header_crc,
        current_lba=current_lba,
        backup_lba=backup_lba,
        first_usable_lba=first_usable,
        last_usable_lba=last_usable,
        disk_guid=bytes_to_guid(disk_guid_raw),
        partition_entry_lba=entry_lba,
        partition_entry_count=entry_count,
        partition_entry_size=entry_size,
        partition_entry_array_crc32=entry_crc,
        raw=bytes(data[:512]),
    )


def verify_gpt_header_crc(data: bytes) -> bool:
    """Recompute the GPT header CRC32 and compare it with the stored value."""
    if len(data) < GPT_HEADER_SIZE:
        return False
    stored = struct.unpack_from("<I", data, 0x10)[0]
    zeroed = bytearray(data[:GPT_HEADER_SIZE])
    zeroed[0x10:0x14] = b"\x00\x00\x00\x00"
    return crc32(bytes(zeroed)) == stored


def parse_gpt_entries(data: bytes, count: int, entry_size: int = GPT_ENTRY_SIZE) -> list[GptEntry]:
    """Parse a GPT partition entry array."""
    entries: list[GptEntry] = []
    for i in range(count):
        off = i * entry_size
        chunk = data[off:off + entry_size]
        if len(chunk) < entry_size:
            break
        entries.append(GptEntry.from_bytes(chunk, i))
    return entries


def build_gpt_header(
    current_lba: int,
    backup_lba: int,
    first_usable_lba: int,
    last_usable_lba: int,
    disk_guid: str,
    partition_entry_lba: int,
    partition_entry_count: int,
    partition_entry_size: int,
    partition_entry_array_crc32: int,
    revision: int = 0x00010000,
) -> bytes:
    """Build a 512 byte GPT header sector with a correct CRC32."""
    body = struct.pack(
        GPT_HEADER_STRUCT,
        GPT_SIGNATURE,
        revision,
        GPT_HEADER_SIZE,
        0,
        0,
        current_lba,
        backup_lba,
        first_usable_lba,
        last_usable_lba,
        guid_to_bytes(disk_guid),
        partition_entry_lba,
        partition_entry_count,
        partition_entry_size,
        partition_entry_array_crc32,
    )
    crc = crc32(body[:GPT_HEADER_SIZE])
    body = body[:0x10] + struct.pack("<I", crc) + body[0x14:]
    return body.ljust(512, b"\x00")


def build_gpt_entry(
    index: int,
    type_guid: str,
    unique_guid: str,
    first_lba: int,
    last_lba: int,
    attributes: int = 0,
    name: str = "",
) -> GptEntry:
    """Create a GPT entry."""
    return GptEntry(
        index=index,
        type_guid=type_guid,
        unique_guid=unique_guid,
        first_lba=first_lba,
        last_lba=last_lba,
        attributes=attributes,
        name=name,
    )


def build_protective_mbr(total_sectors: int) -> bytes:
    """Build the protective MBR that precedes a GPT disk.

    The single partition entry claims the whole disk with type ``0xEE`` and
    the boot signature is written so that legacy BIOS software refuses to
    touch the disk.
    """
    if total_sectors > 0xFFFFFFFF:
        total_sectors = 0xFFFFFFFF
    entry = struct.pack(
        "<BBBBBBBBII",
        0x00,              # not active
        0x00, 0x02, 0x00,  # head 0, sector 2, cylinder 0
        MBR_TYPE_GPT_PROTECTIVE,
        0xFE, 0xFF, 0xFF,  # head/sector/cylinder marker
        1,                 # start LBA
        total_sectors - 1, # sector count
    )
    sector = bytearray(b"\x00" * 512)
    sector[0x1BE:0x1BE + 16] = entry
    sector[0x1FE:0x200] = MBR_BOOT_SIGNATURE
    return bytes(sector)


def gpt_layout(total_sectors: int, entry_count: int = 128) -> dict[str, int]:
    """Compute the canonical GPT layout for a disk of ``total_sectors``."""
    entry_size = GPT_ENTRY_SIZE
    array_sectors = (entry_count * entry_size + 511) // 512
    last_lba = total_sectors - 1
    return {
        "primary_header_lba": GPT_HEADER_LBA,
        "primary_entry_lba": GPT_HEADER_LBA + 1,
        "primary_entry_sectors": array_sectors,
        "backup_entry_lba": last_lba - array_sectors + 1,
        "backup_header_lba": last_lba,
        "first_usable_lba": GPT_HEADER_LBA + 1 + array_sectors,
        "last_usable_lba": last_lba - array_sectors,
        "entry_count": entry_count,
        "entry_size": entry_size,
        "total_sectors": total_sectors,
    }
