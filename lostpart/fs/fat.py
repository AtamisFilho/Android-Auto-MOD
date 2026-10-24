"""FAT12/FAT16/FAT32 probe and read-only directory browser.

The layout implemented here follows the Microsoft [MS-FAT] specification
("FAT File System Specification") and the classic BIOS Parameter Block:

* ``BPB_BytsPerSec`` (0x0B), ``BPB_SecPerClus`` (0x0D), ``BPB_RsvdSecCnt``
  (0x0E), ``BPB_NumFATs`` (0x10), ``BPB_RootEntCnt`` (0x11), ``BPB_TotSec16``
  (0x13), ``BPB_FATSz16`` (0x16), ``BPB_TotSec32`` (0x20), ``BPB_FATSz32``
  (0x24) and ``BPB_RootClus`` (0x2C),
* the volume identifier and label, which live at different offsets for
  FAT32 (0x40/0x44) and for FAT12/FAT16 (0x27/0x2B),
* the file system type string, at 0x4F for FAT32 ("FAT32   ") and at 0x36
  for FAT12/FAT16 ("FAT12   " / "FAT16   ").

The module serves the whole family: the concrete variant is reported through
``ProbeResult.fs_type`` while :data:`FS_TYPE` marks the family.  Everything
is read-only and defensive: damaged disks must produce an empty listing
instead of an exception.
"""

from __future__ import annotations

import datetime
import logging
import struct
from dataclasses import dataclass

from ..constants import (
    FAT12_SIGNATURE,
    FAT16_OFF_FS_TYPE,
    FAT16_OFF_VOLUME_ID,
    FAT16_OFF_VOLUME_LABEL,
    FAT16_SIGNATURE,
    FAT32_SIGNATURE,
    FAT_OFF_BOOT_SIGNATURE,
    FAT_OFF_BOOT_SECTOR_BACKUP,
    FAT_OFF_BYTES_PER_SECTOR,
    FAT_OFF_EXTENDED_BOOT_SIGNATURE,
    FAT_OFF_FAT_SIZE_16,
    FAT_OFF_FAT_SIZE_32,
    FAT_OFF_FSINFO,
    FAT_OFF_FS_TYPE,
    FAT_OFF_NUM_FATS,
    FAT_OFF_OEM,
    FAT_OFF_RESERVED_SECTORS,
    FAT_OFF_ROOT_CLUSTER_32,
    FAT_OFF_ROOT_ENTRIES,
    FAT_OFF_SECTORS_PER_CLUSTER,
    FAT_OFF_TOTAL_SECTORS_16,
    FAT_OFF_TOTAL_SECTORS_32,
    FAT_OFF_VOLUME_ID,
    FAT_OFF_VOLUME_LABEL,
    VALID_BYTES_PER_SECTOR,
)
from .base import DirEntry, ProbeContext, ProbeResult

logger = logging.getLogger(__name__)

#: Family identifier of this module; the concrete variant is reported by
#: ``ProbeResult.fs_type``.
FS_TYPE = "fat"

# --------------------------------------------------------------------------
# Constants that are not part of :mod:`lostpart.constants`
# --------------------------------------------------------------------------

#: Boot signature (0x55AA) expected at the end of the boot sector.
FAT_BOOT_SIGNATURE = b"\x55\xaa"

#: Extended boot signature written by FAT32 formatters.
FAT_EXTENDED_BOOT_SIGNATURE = b"\x29"

#: Size of a FAT12 BIOS Parameter Block.
FAT12_OFF_FAT_SIZE = 0x24

#: Size of a single directory entry in bytes.
FAT_DIRECTORY_ENTRY_SIZE = 32

#: Cluster numbers are 2 based; cluster 2 is the first data cluster.
FAT_FIRST_DATA_CLUSTER = 2

#: Maximum number of clusters of a FAT12 volume [MS-FAT].
FAT12_MAX_CLUSTERS = 4085

#: Maximum number of clusters of a FAT16 volume [MS-FAT].
FAT16_MAX_CLUSTERS = 65525

#: Largest FAT table kept completely in memory (bytes).
FAT_MAX_CACHED_FAT_BYTES = 64 * 1024 * 1024

#: Chunk size used to read a FAT that is too large to be cached.
FAT_FAT_CHUNK_SIZE = 64 * 1024

#: Maximum number of clusters visited while walking one directory.
FAT_MAX_CHAIN_CLUSTERS = 1 << 16

#: Maximum number of bytes collected while walking one directory.
FAT_MAX_DIRECTORY_BYTES = 16 * 1024 * 1024

#: Maximum number of entries returned for a single directory.
FAT_MAX_DIRECTORY_ENTRIES = 100_000

#: Directory entry attributes (offset 0x0B).
FAT_ATTR_READ_ONLY = 0x01
FAT_ATTR_HIDDEN = 0x02
FAT_ATTR_SYSTEM = 0x04
FAT_ATTR_VOLUME_ID = 0x08
FAT_ATTR_DIRECTORY = 0x10
FAT_ATTR_ARCHIVE = 0x20
FAT_ATTR_LONG_NAME = 0x0F

#: First byte of a deleted directory entry.
FAT_DELETED_MARKER = 0xE5

#: Long file name entry: sequence number flag of the last logical entry.
FAT_LFN_LAST_FLAG = 0x40

#: Long file name entry: sequence number mask.
FAT_LFN_SEQUENCE_MASK = 0x3F

#: Long file name entry: offset of the first five UTF-16 code units.
FAT_LFN_CHARS_OFFSET_1 = 1

#: Long file name entry: offset of the remaining six UTF-16 code units.
FAT_LFN_CHARS_OFFSET_2 = 14


@dataclass(frozen=True)
class _Geometry:
    """Decoded BIOS Parameter Block of a FAT volume."""

    variant: str
    bytes_per_sector: int
    sectors_per_cluster: int
    reserved_sectors: int
    num_fats: int
    root_entries: int
    fat_size: int
    total_sectors: int
    cluster_count: int
    root_cluster: int
    data_start_sector: int
    volume_id: int | None
    label: str
    fs_type_string: str | None
    hard_problems: tuple[str, ...]
    soft_problems: tuple[str, ...]

    @property
    def is_fat32(self) -> bool:
        """True when the volume uses a FAT32 layout."""
        return self.variant == "fat32"


def _read_boot(ctx: ProbeContext) -> bytes | None:
    """Read the boot sector of the candidate volume, or ``None`` on failure."""
    try:
        boot = ctx.read(0, 512)
    except Exception:  # pragma: no cover - device level failure
        logger.debug("fat: boot sector could not be read", exc_info=True)
        return None
    if len(boot) < 512:
        logger.debug("fat: short boot sector (%d bytes)", len(boot))
        return None
    return boot


def _u16(boot: bytes, offset: int) -> int:
    """Read a little endian 16 bit value, 0 when the buffer is too short."""
    try:
        return struct.unpack_from("<H", boot, offset)[0]
    except struct.error:
        return 0


def _u32(boot: bytes, offset: int) -> int:
    """Read a little endian 32 bit value, 0 when the buffer is too short."""
    try:
        return struct.unpack_from("<I", boot, offset)[0]
    except struct.error:
        return 0


def _read_fs_type_string(boot: bytes, offset: int) -> str | None:
    """Return the file system type string stored at *offset*, if any."""
    raw = boot[offset : offset + 8]
    if len(raw) < 8:
        return None
    text = raw.decode("latin-1", errors="replace")
    if text in ("FAT32   ", "FAT16   ", "FAT12   "):
        return text
    return None


def _clean_label(raw: bytes) -> str:
    """Decode a space padded (or NUL padded) volume label."""
    return raw.decode("latin-1", errors="replace").strip("\x00 ").strip()


def _parse_bpb(boot: bytes) -> _Geometry:
    """Decode the BIOS Parameter Block of a FAT volume.

    The returned geometry lists the problems that were found: ``hard_problems``
    are values that violate the specification, ``soft_problems`` are values
    that are merely implausible (for example a volume that is larger than the
    device it lives on).
    """
    bytes_per_sector = _u16(boot, FAT_OFF_BYTES_PER_SECTOR)
    sectors_per_cluster = boot[FAT_OFF_SECTORS_PER_CLUSTER]
    reserved_sectors = _u16(boot, FAT_OFF_RESERVED_SECTORS)
    num_fats = boot[FAT_OFF_NUM_FATS]
    root_entries = _u16(boot, FAT_OFF_ROOT_ENTRIES)
    total_sectors_16 = _u16(boot, FAT_OFF_TOTAL_SECTORS_16)
    fat_size_16 = _u16(boot, FAT_OFF_FAT_SIZE_16)
    total_sectors_32 = _u32(boot, FAT_OFF_TOTAL_SECTORS_32)
    fat_size_32 = _u32(boot, FAT_OFF_FAT_SIZE_32)
    root_cluster = _u32(boot, FAT_OFF_ROOT_CLUSTER_32)

    total_sectors = total_sectors_16 if total_sectors_16 else total_sectors_32

    hard: list[str] = []
    soft: list[str] = []

    if bytes_per_sector not in VALID_BYTES_PER_SECTOR:
        hard.append(f"bytes_per_sector={bytes_per_sector} invalid")
    if sectors_per_cluster not in (1, 2, 4, 8, 16, 32, 64, 128):
        hard.append(f"sectors_per_cluster={sectors_per_cluster} invalid")
    if reserved_sectors == 0:
        hard.append("reserved_sectors=0 invalid")
    if num_fats == 0 or num_fats > 4:
        hard.append(f"num_fats={num_fats} invalid")
    if total_sectors == 0:
        hard.append("total_sectors=0 invalid")

    # FAT32 keeps its root directory in a cluster chain, FAT12/FAT16 in a
    # fixed area of ``root_entries`` entries.
    if root_entries == 0:
        variant = "fat32"
        fat_size = fat_size_32 or fat_size_16
        root_dir_sectors = 0
    else:
        variant = "fat12/16"
        fat_size = fat_size_16
        if fat_size == 0:
            # FAT12 stores the number of sectors per FAT in a single byte.
            fat_size = boot[FAT12_OFF_FAT_SIZE]
        root_dir_sectors = ((root_entries * FAT_DIRECTORY_ENTRY_SIZE) + 511) // 512

    if fat_size == 0:
        hard.append("fat_size=0 invalid")
    if variant == "fat32" and root_cluster == 0:
        hard.append("root_cluster=0 invalid")

    if sectors_per_cluster > 0 and fat_size > 0:
        cluster_count = max(
            0,
            (total_sectors - reserved_sectors - num_fats * fat_size)
            // sectors_per_cluster,
        )
    else:
        cluster_count = 0

    # The file system type string is authoritative for FAT12 versus FAT16;
    # the cluster count is only a heuristic.
    fs_type_string = None
    if variant == "fat32":
        fs_type_string = _read_fs_type_string(boot, FAT_OFF_FS_TYPE)
        if fs_type_string == FAT32_SIGNATURE.decode("ascii"):
            variant = "fat32"
        elif fs_type_string is not None:
            soft.append(
                f"file system type string {fs_type_string!r} conflicts with the BPB "
                "geometry (FAT32)"
            )
    else:
        fs_type_string = _read_fs_type_string(boot, FAT16_OFF_FS_TYPE)
        if fs_type_string == FAT16_SIGNATURE.decode("ascii"):
            variant = "fat16"
        elif fs_type_string == FAT12_SIGNATURE.decode("ascii"):
            variant = "fat12"
        elif cluster_count < FAT12_MAX_CLUSTERS:
            variant = "fat12"
        elif cluster_count < FAT16_MAX_CLUSTERS:
            variant = "fat16"
        else:
            variant = "fat16"
            soft.append(
                f"cluster_count={cluster_count} exceeds the FAT16 limit, "
                "the volume looks like a FAT32 with a fixed root directory"
            )

    data_start_sector = reserved_sectors + num_fats * fat_size + root_dir_sectors
    if total_sectors and data_start_sector > total_sectors:
        soft.append(
            f"data region starts at sector {data_start_sector} beyond the "
            f"declared size of {total_sectors} sectors"
        )

    if variant == "fat32":
        volume_id = _u32(boot, FAT_OFF_VOLUME_ID)
        label = _clean_label(boot[FAT_OFF_VOLUME_LABEL : FAT_OFF_VOLUME_LABEL + 11])
    else:
        volume_id = _u32(boot, FAT16_OFF_VOLUME_ID)
        label = _clean_label(
            boot[FAT16_OFF_VOLUME_LABEL : FAT16_OFF_VOLUME_LABEL + 11]
        )

    return _Geometry(
        variant=variant,
        bytes_per_sector=bytes_per_sector,
        sectors_per_cluster=sectors_per_cluster,
        reserved_sectors=reserved_sectors,
        num_fats=num_fats,
        root_entries=root_entries,
        fat_size=fat_size,
        total_sectors=total_sectors,
        cluster_count=cluster_count,
        root_cluster=root_cluster,
        data_start_sector=data_start_sector,
        volume_id=volume_id,
        label=label,
        fs_type_string=fs_type_string,
        hard_problems=tuple(hard),
        soft_problems=tuple(soft),
    )


def _to_device_sectors(fs_sectors: int, bytes_per_sector: int, sector_size: int) -> int:
    """Convert a sector count of the filesystem into device sectors."""
    if sector_size <= 0:
        return fs_sectors
    return fs_sectors * bytes_per_sector // sector_size


def _dos_timestamp_to_epoch(date: int, time_value: int) -> float | None:
    """Convert a DOS date/time pair into a POSIX timestamp."""
    if date == 0:
        return None
    year = 1980 + ((date >> 9) & 0x7F)
    month = (date >> 5) & 0x0F
    day = date & 0x1F
    hour = (time_value >> 11) & 0x1F
    minute = (time_value >> 5) & 0x3F
    second = (time_value & 0x1F) * 2
    if not (1 <= month <= 12) or not (1 <= day <= 31):
        return None
    try:
        stamp = datetime.datetime(
            year, month, day, hour, minute, second, tzinfo=datetime.timezone.utc
        )
    except ValueError:
        return None
    return stamp.timestamp()


class _FatTable:
    """Read-only view on a FAT12, FAT16 or FAT32 allocation table."""

    def __init__(self, ctx: ProbeContext, geom: _Geometry) -> None:
        self._ctx = ctx
        self._variant = geom.variant
        self._offset = geom.reserved_sectors * geom.bytes_per_sector
        self._length = geom.fat_size * geom.bytes_per_sector
        self._cached: bytes | None = None
        self._chunks: dict[int, bytes] = {}
        if 0 < self._length <= FAT_MAX_CACHED_FAT_BYTES:
            self._cached = self._read(0, self._length)

    def _read(self, offset: int, size: int) -> bytes:
        """Read *size* bytes at *offset* inside the FAT region."""
        if size <= 0:
            return b""
        try:
            return self._ctx.read(self._offset + offset, size)
        except Exception:  # pragma: no cover - device level failure
            logger.debug("fat: FAT region read failed", exc_info=True)
            return b""

    def _chunk(self, chunk_index: int) -> bytes:
        """Return the cached chunk *chunk_index* of the FAT region."""
        chunk = self._chunks.get(chunk_index)
        if chunk is None:
            chunk = self._read(chunk_index * FAT_FAT_CHUNK_SIZE, FAT_FAT_CHUNK_SIZE)
            self._chunks[chunk_index] = chunk
        return chunk

    def _raw(self, offset: int, size: int) -> bytes:
        """Return *size* bytes of the FAT region starting at *offset*."""
        if self._cached is not None:
            return self._cached[offset : offset + size]
        chunk_index, inner = divmod(offset, FAT_FAT_CHUNK_SIZE)
        chunk = self._chunk(chunk_index)
        return chunk[inner : inner + size]

    def entry(self, cluster: int) -> int:
        """Return the FAT entry of *cluster* (0 when it cannot be read)."""
        if cluster < 0:
            return 0
        if self._variant == "fat12":
            offset = cluster + (cluster >> 1)
            raw = self._raw(offset, 2)
            if len(raw) < 2:
                return 0
            if cluster & 1:
                return (raw[0] >> 4) | (raw[1] << 4)
            return raw[0] | ((raw[1] & 0x0F) << 8)
        if self._variant == "fat16":
            raw = self._raw(cluster * 2, 2)
            if len(raw) < 2:
                return 0
            return struct.unpack_from("<H", raw, 0)[0]
        raw = self._raw(cluster * 4, 4)
        if len(raw) < 4:
            return 0
        return struct.unpack_from("<I", raw, 0)[0] & 0x0FFFFFFF

    def is_end_of_chain(self, value: int) -> bool:
        """True when *value* marks the end of a cluster chain."""
        if self._variant == "fat12":
            return value >= 0xFF8
        if self._variant == "fat16":
            return value >= 0xFFF8
        return value >= 0x0FFFFFF8


def _cluster_offset(geom: _Geometry, cluster: int) -> int:
    """Return the byte offset of *cluster* inside the data region."""
    sector = geom.data_start_sector + (cluster - FAT_FIRST_DATA_CLUSTER) * geom.sectors_per_cluster
    return sector * geom.bytes_per_sector


def _read_cluster_chain(
    ctx: ProbeContext, geom: _Geometry, fat: _FatTable, start: int
) -> bytes:
    """Return the raw bytes of the cluster chain starting at *start*."""
    if start < FAT_FIRST_DATA_CLUSTER:
        return b""
    chunks: list[bytes] = []
    visited: set[int] = set()
    cluster = start
    total = 0
    while cluster >= FAT_FIRST_DATA_CLUSTER:
        if cluster in visited or len(visited) >= FAT_MAX_CHAIN_CLUSTERS:
            logger.debug("fat: cluster chain loop at cluster %d", cluster)
            break
        visited.add(cluster)
        try:
            data = ctx.read(
                _cluster_offset(geom, cluster), geom.bytes_per_sector * geom.sectors_per_cluster
            )
        except Exception:  # pragma: no cover - device level failure
            logger.debug("fat: cluster %d unreadable", cluster, exc_info=True)
            break
        if not data:
            break
        chunks.append(data)
        total += len(data)
        if total >= FAT_MAX_DIRECTORY_BYTES:
            break
        cluster = fat.entry(cluster)
        if fat.is_end_of_chain(cluster):
            break
    return b"".join(chunks)


def _short_name(raw: bytes) -> str:
    """Convert an 8.3 short name into its printable form."""
    if len(raw) < 11:
        raw = raw.ljust(11, b"\x00")
    name = raw[0:8].decode("latin-1", errors="replace").rstrip()
    extension = raw[8:11].decode("latin-1", errors="replace").rstrip()
    if not name:
        return ""
    if name[0] == "\x05":
        # 0xE5 is escaped as 0x05 in short names.
        name = "\u2026" + name[1:]
    if extension:
        return f"{name}.{extension}"
    return name


def _decode_lfn_part(raw: bytes) -> str:
    """Decode one long file name fragment."""
    try:
        text = raw.decode("utf-16-le", errors="replace")
    except UnicodeDecodeError:  # pragma: no cover - defensive
        return ""
    return text.replace("\ufffd", "").rstrip("\x00\uffff")


def _parse_directory(data: bytes, is_fat32: bool) -> list[DirEntry]:
    """Parse the 32 byte directory entries contained in *data*."""
    entries: list[DirEntry] = []
    lfn_parts: list[str] = []
    position = 0
    total = len(data)
    while position + FAT_DIRECTORY_ENTRY_SIZE <= total:
        entry = data[position : position + FAT_DIRECTORY_ENTRY_SIZE]
        position += FAT_DIRECTORY_ENTRY_SIZE
        first = entry[0]
        if first == 0x00:
            # Unused entry: the directory ends here.
            break
        if first == FAT_DELETED_MARKER:
            lfn_parts.clear()
            continue
        attributes = entry[11]
        if (attributes & 0x3F) == FAT_ATTR_LONG_NAME:
            lfn_parts.append(
                _decode_lfn_part(entry[FAT_LFN_CHARS_OFFSET_1 : FAT_LFN_CHARS_OFFSET_1 + 10])
                + _decode_lfn_part(
                    entry[FAT_LFN_CHARS_OFFSET_2 : FAT_LFN_CHARS_OFFSET_2 + 12]
                )
            )
            continue

        name = ""
        if lfn_parts:
            name = "".join(reversed(lfn_parts)).rstrip("\x00\uffff")
            lfn_parts.clear()
        else:
            name = _short_name(entry[0:11])
        if attributes & FAT_ATTR_VOLUME_ID:
            # Volume label entries carry no file.
            continue
        if not name or name in (".", ".."):
            continue

        first_cluster = struct.unpack_from("<H", entry, 26)[0]
        if is_fat32:
            first_cluster |= struct.unpack_from("<H", entry, 20)[0] << 16
        size = struct.unpack_from("<I", entry, 28)[0]
        modified = _dos_timestamp_to_epoch(
            struct.unpack_from("<H", entry, 24)[0],
            struct.unpack_from("<H", entry, 22)[0],
        )
        is_dir = bool(attributes & FAT_ATTR_DIRECTORY)
        entries.append(
            DirEntry(
                name=name,
                is_dir=is_dir,
                size=0 if is_dir else size,
                modified=modified,
                inode=first_cluster or None,
                is_hidden=bool(attributes & FAT_ATTR_HIDDEN),
            )
        )
        if len(entries) >= FAT_MAX_DIRECTORY_ENTRIES:
            break
    return entries


def _read_root_directory(
    ctx: ProbeContext, geom: _Geometry, fat: _FatTable
) -> list[DirEntry]:
    """List the entries of the root directory."""
    if geom.is_fat32:
        data = _read_cluster_chain(ctx, geom, fat, geom.root_cluster)
    else:
        offset = (
            geom.reserved_sectors + geom.num_fats * geom.fat_size
        ) * geom.bytes_per_sector
        size = geom.root_entries * FAT_DIRECTORY_ENTRY_SIZE
        try:
            data = ctx.read(offset, size)
        except Exception:  # pragma: no cover - device level failure
            logger.debug("fat: root directory unreadable", exc_info=True)
            data = b""
    if not data:
        return []
    return _parse_directory(data, geom.is_fat32)


def _read_sub_directory(
    ctx: ProbeContext, geom: _Geometry, fat: _FatTable, cluster: int
) -> list[DirEntry]:
    """List the entries of the sub directory stored in *cluster*."""
    data = _read_cluster_chain(ctx, geom, fat, cluster)
    if not data:
        return []
    return _parse_directory(data, geom.is_fat32)


def detect(ctx: ProbeContext) -> ProbeResult | None:
    """Detect a FAT12, FAT16 or FAT32 volume at the start of the candidate.

    The volume is recognised through the BIOS Parameter Block.  A file system
    type string ("FAT32   ", "FAT16   " or "FAT12   ") is the strongest
    evidence; volumes without that string are still reported when the BPB
    geometry is fully consistent, with a lower confidence.

    * 1.0 -- type string present and every structural field consistent,
    * 0.9 -- type string present, one soft field inconsistent,
    * 0.6 -- type string present but a hard field is invalid, or the type
      string is absent while the geometry is consistent,
    * 0.3 -- weak match only.
    """
    boot = _read_boot(ctx)
    if boot is None:
        return None

    geom = _parse_bpb(boot)

    evidence: list[str] = []
    hard = list(geom.hard_problems)
    soft = list(geom.soft_problems)

    oem = boot[FAT_OFF_OEM : FAT_OFF_OEM + 8]
    if any(char not in b"\x00" for char in oem):
        evidence.append(f"OEM name {oem.decode('latin-1', errors='replace')!r} present")

    if geom.fs_type_string is not None:
        offset = FAT_OFF_FS_TYPE if geom.variant == "fat32" else FAT16_OFF_FS_TYPE
        evidence.append(
            f"file system type {geom.fs_type_string!r} at offset {offset}"
        )
    else:
        evidence.append("file system type string absent")

    if geom.bytes_per_sector in VALID_BYTES_PER_SECTOR:
        evidence.append(f"bytes_per_sector={geom.bytes_per_sector} valid")
    if geom.sectors_per_cluster in (1, 2, 4, 8, 16, 32, 64, 128):
        evidence.append(f"sectors_per_cluster={geom.sectors_per_cluster} valid")
    if geom.reserved_sectors:
        evidence.append(f"reserved_sectors={geom.reserved_sectors} valid")
    if 1 <= geom.num_fats <= 4:
        evidence.append(f"num_fats={geom.num_fats} valid")
    if geom.fat_size:
        evidence.append(f"fat_size={geom.fat_size} sectors valid")
    if geom.total_sectors:
        evidence.append(f"total_sectors={geom.total_sectors} valid")

    if geom.variant == "fat32":
        evidence.append(
            f"root_entries=0, the root directory is the cluster chain "
            f"starting at cluster {geom.root_cluster}"
        )
        if boot[FAT_OFF_EXTENDED_BOOT_SIGNATURE : FAT_OFF_EXTENDED_BOOT_SIGNATURE + 1] == FAT_EXTENDED_BOOT_SIGNATURE:
            evidence.append("extended boot signature 0x29 present")
        else:
            soft.append("extended boot signature 0x29 absent")
        fsinfo_sector = _u16(boot, FAT_OFF_FSINFO)
        if fsinfo_sector:
            evidence.append(f"FSInfo sector {fsinfo_sector} referenced")
        if boot[FAT_OFF_BOOT_SECTOR_BACKUP : FAT_OFF_BOOT_SECTOR_BACKUP + 1]:
            evidence.append(
                f"backup boot sector {boot[FAT_OFF_BOOT_SECTOR_BACKUP]} referenced"
            )
    else:
        evidence.append(
            f"root_entries={geom.root_entries}, the root directory is a fixed "
            f"area of {geom.root_entries} entries"
        )
        if geom.fs_type_string is None:
            evidence.append(
                f"cluster_count={geom.cluster_count} indicates {geom.variant.upper()}"
            )

    if boot[FAT_OFF_BOOT_SIGNATURE : FAT_OFF_BOOT_SIGNATURE + 2] == FAT_BOOT_SIGNATURE:
        evidence.append("boot signature 0x55AA present")
    else:
        soft.append("boot signature 0x55AA absent")

    volume_bytes = ctx.volume_bytes()
    if geom.total_sectors and geom.bytes_per_sector:
        if geom.total_sectors * geom.bytes_per_sector > volume_bytes:
            soft.append(
                f"the volume claims {geom.total_sectors} sectors but only "
                f"{volume_bytes} bytes are left on the device"
            )
        else:
            evidence.append("the volume fits in the remaining device space")

    if geom.fs_type_string is None and not hard and not soft:
        evidence.append(
            f"file system type string absent, geometry consistent with "
            f"{geom.variant.upper()}"
        )

    if geom.fs_type_string is None:
        # Without the type string only a fully consistent BPB is accepted;
        # a broken geometry is indistinguishable from random data.
        if hard:
            evidence.extend(hard)
            return None
        confidence = 0.6 if not soft else 0.3
        evidence.extend(soft)
    elif hard:
        confidence = 0.6 if len(hard) == 1 else 0.3
        evidence.extend(hard)
        evidence.extend(soft)
    elif soft:
        confidence = 0.9 if len(soft) == 1 else 0.6
        evidence.extend(soft)
    else:
        confidence = 1.0

    device_sectors = _to_device_sectors(
        geom.total_sectors, geom.bytes_per_sector, ctx.sector_size
    )

    details: dict[str, object] = {
        "fs_type": geom.variant,
        "label": geom.label,
        "bytes_per_sector": geom.bytes_per_sector,
        "sectors_per_cluster": geom.sectors_per_cluster,
        "total_sectors": device_sectors,
        "cluster_count": geom.cluster_count,
        "reserved_sectors": geom.reserved_sectors,
        "num_fats": geom.num_fats,
        "root_entries": geom.root_entries,
        "fat_size": geom.fat_size,
        "data_start_sector": geom.data_start_sector,
        "root_cluster": geom.root_cluster,
        "volume_id": geom.volume_id,
    }
    return ProbeResult(
        fs_type=geom.variant,
        label=geom.label,
        confidence=confidence,
        details=details,
        evidence=tuple(evidence),
    )


def read_directory(
    ctx: ProbeContext, path: tuple[str, ...] = ()
) -> list[DirEntry]:
    """List the entries of a directory of the FAT volume at the candidate.

    ``path`` is a tuple of directory names relative to the volume root.  For
    FAT12/FAT16 the root directory is the fixed area of ``root_entries``
    entries that follows the FAT copies, for FAT32 it is the cluster chain
    that starts at ``BPB_RootClus``.
    """
    try:
        boot = _read_boot(ctx)
        if boot is None:
            return []
        geom = _parse_bpb(boot)
        if geom.bytes_per_sector <= 0 or geom.sectors_per_cluster <= 0:
            return []
        if geom.hard_problems:
            logger.debug("fat: refusing to browse a broken volume: %s", geom.hard_problems)
            return []

        fat = _FatTable(ctx, geom)

        def _list(cluster: int | None) -> list[DirEntry]:
            """List a directory; ``None`` means the FAT12/FAT16 root area."""
            if cluster is None:
                return _read_root_directory(ctx, geom, fat)
            return _read_sub_directory(ctx, geom, fat, cluster)

        # FAT32 keeps its root directory in a cluster chain, FAT12/FAT16 in a
        # fixed area that is not addressed by a cluster number.
        current: int | None = geom.root_cluster if geom.is_fat32 else None
        for component in path:
            if not component:
                continue
            entries = _list(current)
            match = next(
                (
                    entry
                    for entry in entries
                    if entry.is_dir and entry.name.lower() == component.lower()
                ),
                None,
            )
            if match is None or match.inode is None:
                return []
            current = match.inode
        return _list(current)
    except Exception:  # pragma: no cover - defensive, corrupt volumes
        logger.warning("fat: directory listing failed", exc_info=True)
        return []
