"""exFAT probe and read-only directory browser.

The on-disk layout implemented here follows the Microsoft *exFAT File System
Specification* (revision 1.00) that ships with the Win32 documentation:

https://learn.microsoft.com/en-us/windows/win32/fileio/exfat-specification

Only the parts that are needed to (a) recognise an exFAT volume and (b) list
its directory tree are implemented:

* the Main Boot Sector (specification section 3.1),
* the allocation table / FAT (section 4.1),
* the directory entry sets (sections 6 and 7).

A *directory entry set* is made of one primary entry (a File Directory Entry
for regular files and directories) followed by a number of secondary entries
described by the ``SecondaryCount`` field of the primary entry.  For a file
the set contains a Stream Extension Directory Entry (which carries the first
cluster and the data length) and one or more File Name Directory Entries
(which carry the UTF-16 name).

The module is deliberately defensive: it runs against damaged disks, so every
malformed structure degrades to "no result" instead of raising.
"""

from __future__ import annotations

import datetime
import logging
import struct
from dataclasses import dataclass

from ..constants import (
    EXFAT_BOOT_SECTOR_SIZE,
    EXFAT_OEM_ID,
    EXFAT_OFF_BOOT_SIGNATURE,
    EXFAT_OFF_BYTES_PER_SECTOR_SHIFT,
    EXFAT_OFF_CLUSTER_COUNT,
    EXFAT_OFF_CLUSTER_HEAP_OFFSET,
    EXFAT_OFF_FAT_LENGTH,
    EXFAT_OFF_FAT_OFFSET,
    EXFAT_OFF_OEM,
    EXFAT_OFF_ROOT_DIR_CLUSTER,
    EXFAT_OFF_SECTORS_PER_CLUSTER_SHIFT,
    EXFAT_OFF_VOLUME_LENGTH,
    EXFAT_OFF_VOLUME_SERIAL,
)
from .base import DirEntry, ProbeContext, ProbeResult

logger = logging.getLogger(__name__)

#: Family identifier of this module.
FS_TYPE = "exfat"

# --------------------------------------------------------------------------
# Constants that are not part of :mod:`lostpart.constants`
# --------------------------------------------------------------------------

#: Boot signature (0x55AA) expected at the end of the boot sector.
EXFAT_BOOT_SIGNATURE = b"\x55\xaa"

#: Offset of the ``NumberOfFats`` field; exFAT always uses exactly one FAT.
EXFAT_OFF_NUMBER_OF_FATS = 0x6E

#: Size of a single directory entry in bytes (specification section 6.1).
EXFAT_DIRECTORY_ENTRY_SIZE = 32

#: Maximum cluster size allowed by the specification (32 KiB).
EXFAT_MAX_CLUSTER_SIZE = 32 * 1024

#: A FAT entry is 32 bits wide (specification section 4.1).
EXFAT_FAT_ENTRY_SIZE = 4

#: Value that marks the end of a cluster chain.
EXFAT_FAT_END_OF_CHAIN = 0xFFFFFFFF

#: First cluster of the cluster heap; cluster numbers are 2 based.
EXFAT_FIRST_DATA_CLUSTER = 2

#: The cluster heap may not contain more than 2**32 clusters.
EXFAT_MAX_CLUSTER_COUNT = 1 << 32

#: Largest FAT table kept completely in memory (bytes).
EXFAT_MAX_CACHED_FAT_BYTES = 64 * 1024 * 1024

#: Chunk size used to read a FAT that is too large to be cached.
EXFAT_FAT_CHUNK_SIZE = 64 * 1024

#: Maximum number of clusters visited while walking one directory.
EXFAT_MAX_CHAIN_CLUSTERS = 1 << 16

#: Maximum number of bytes collected while walking one directory.
EXFAT_MAX_DIRECTORY_BYTES = 16 * 1024 * 1024

#: Maximum number of entries returned for a single directory.
EXFAT_MAX_DIRECTORY_ENTRIES = 100_000

# Directory entry type codes (specification section 7).
EXFAT_ENTRY_ALLOCATION_BITMAP = 0x81
EXFAT_ENTRY_UP_CASE_TABLE = 0x82
EXFAT_ENTRY_VOLUME_LABEL = 0x83
EXFAT_ENTRY_FILE = 0x85
EXFAT_ENTRY_STREAM_EXTENSION = 0xC0
EXFAT_ENTRY_FILE_NAME = 0xC1

# File Directory Entry (specification Table 27).
EXFAT_FILE_OFF_ATTRIBUTES = 4
EXFAT_FILE_OFF_LAST_MODIFIED = 12
EXFAT_FILE_OFF_LAST_MODIFIED_10MS = 21

# Stream Extension Directory Entry (specification Table 33).
EXFAT_STREAM_OFF_NAME_LENGTH = 3
EXFAT_STREAM_OFF_FIRST_CLUSTER = 20
EXFAT_STREAM_OFF_DATA_LENGTH = 24

# File Name Directory Entry (specification Table 34).
EXFAT_NAME_OFF_FILE_NAME = 2
EXFAT_NAME_CHARS_PER_ENTRY = 15

# File attributes (specification Table 28).
EXFAT_ATTR_HIDDEN = 0x02
EXFAT_ATTR_DIRECTORY = 0x10


@dataclass(frozen=True)
class _Boot:
    """Relevant fields of the exFAT Main Boot Sector."""

    bytes_per_sector: int
    sectors_per_cluster: int
    volume_length: int
    fat_offset: int
    fat_length: int
    cluster_heap_offset: int
    cluster_count: int
    root_dir_cluster: int
    volume_serial: int
    number_of_fats: int

    @property
    def cluster_size(self) -> int:
        """Size of one cluster in bytes."""
        return self.bytes_per_sector * self.sectors_per_cluster

    @property
    def fat_bytes(self) -> int:
        """Size of the allocation table in bytes."""
        return self.fat_length * self.bytes_per_sector


def _read_boot(ctx: ProbeContext) -> bytes | None:
    """Read the boot sector of the candidate volume, or ``None`` on failure."""
    try:
        boot = ctx.read(0, EXFAT_BOOT_SECTOR_SIZE)
    except Exception:  # pragma: no cover - device level failure
        logger.debug("exfat: boot sector could not be read", exc_info=True)
        return None
    if len(boot) < EXFAT_BOOT_SECTOR_SIZE:
        logger.debug("exfat: short boot sector (%d bytes)", len(boot))
        return None
    return boot


def _parse_boot(boot: bytes) -> _Boot | None:
    """Decode the boot sector fields, or ``None`` when the buffer is short."""
    try:
        volume_length = struct.unpack_from("<Q", boot, EXFAT_OFF_VOLUME_LENGTH)[0]
        fat_offset = struct.unpack_from("<I", boot, EXFAT_OFF_FAT_OFFSET)[0]
        fat_length = struct.unpack_from("<I", boot, EXFAT_OFF_FAT_LENGTH)[0]
        cluster_heap_offset = struct.unpack_from("<I", boot, EXFAT_OFF_CLUSTER_HEAP_OFFSET)[0]
        cluster_count = struct.unpack_from("<I", boot, EXFAT_OFF_CLUSTER_COUNT)[0]
        root_dir_cluster = struct.unpack_from("<I", boot, EXFAT_OFF_ROOT_DIR_CLUSTER)[0]
        volume_serial = struct.unpack_from("<I", boot, EXFAT_OFF_VOLUME_SERIAL)[0]
    except struct.error:
        logger.debug("exfat: boot sector truncated", exc_info=True)
        return None

    bytes_per_sector = 1 << boot[EXFAT_OFF_BYTES_PER_SECTOR_SHIFT]
    sectors_per_cluster = 1 << boot[EXFAT_OFF_SECTORS_PER_CLUSTER_SHIFT]
    return _Boot(
        bytes_per_sector=bytes_per_sector,
        sectors_per_cluster=sectors_per_cluster,
        volume_length=volume_length,
        fat_offset=fat_offset,
        fat_length=fat_length,
        cluster_heap_offset=cluster_heap_offset,
        cluster_count=cluster_count,
        root_dir_cluster=root_dir_cluster,
        volume_serial=volume_serial,
        number_of_fats=boot[EXFAT_OFF_NUMBER_OF_FATS],
    )


def _to_device_sectors(fs_sectors: int, bytes_per_sector: int, sector_size: int) -> int:
    """Convert a sector count of the filesystem into device sectors."""
    if sector_size <= 0:
        return fs_sectors
    return fs_sectors * bytes_per_sector // sector_size


def _dos_timestamp_to_epoch(value: int, tenths: int = 0) -> float | None:
    """Convert an exFAT timestamp into a POSIX timestamp.

    exFAT stores a DOS style date/time pair (specification Table 29) in the
    upper/lower 16 bits of the 32 bit timestamp field, optionally refined by
    a 10 millisecond increment.
    """
    if value == 0:
        return None
    date = (value >> 16) & 0xFFFF
    time = value & 0xFFFF
    year = 1980 + ((date >> 9) & 0x7F)
    month = (date >> 5) & 0x0F
    day = date & 0x1F
    hour = (time >> 11) & 0x1F
    minute = (time >> 5) & 0x3F
    second = (time & 0x1F) * 2
    if not (1 <= month <= 12) or not (1 <= day <= 31):
        return None
    try:
        stamp = datetime.datetime(
            year, month, day, hour, minute, second, tzinfo=datetime.timezone.utc
        )
    except ValueError:
        return None
    return stamp.timestamp() + (tenths % 100) * 0.01


class _FatTable:
    """Read-only view on the exFAT allocation table.

    The table is cached in memory when it is small enough (which is the
    normal case).  Larger tables are read on demand in chunks.
    """

    def __init__(self, ctx: ProbeContext, boot: _Boot) -> None:
        self._ctx = ctx
        self._offset = boot.fat_offset * boot.bytes_per_sector
        self._length = boot.fat_bytes
        self._cached: bytes | None = None
        self._chunks: dict[int, bytes] = {}
        if 0 < self._length <= EXFAT_MAX_CACHED_FAT_BYTES:
            self._cached = self._read(0, self._length)

    def _read(self, offset: int, size: int) -> bytes:
        """Read *size* bytes at *offset* inside the FAT region."""
        if size <= 0:
            return b""
        try:
            return self._ctx.read(self._offset + offset, size)
        except Exception:  # pragma: no cover - device level failure
            logger.debug("exfat: FAT region read failed", exc_info=True)
            return b""

    def _chunk(self, chunk_index: int) -> bytes:
        """Return the cached chunk *chunk_index* of the FAT region."""
        chunk = self._chunks.get(chunk_index)
        if chunk is None:
            chunk = self._read(
                chunk_index * EXFAT_FAT_CHUNK_SIZE, EXFAT_FAT_CHUNK_SIZE
            )
            self._chunks[chunk_index] = chunk
        return chunk

    def entry(self, cluster: int) -> int:
        """Return the FAT entry of *cluster* (0 when it cannot be read)."""
        if cluster < 0:
            return 0
        offset = cluster * EXFAT_FAT_ENTRY_SIZE
        if self._cached is not None:
            if offset + EXFAT_FAT_ENTRY_SIZE > len(self._cached):
                return 0
            return struct.unpack_from("<I", self._cached, offset)[0]
        chunk_index, inner = divmod(offset, EXFAT_FAT_CHUNK_SIZE)
        chunk = self._chunk(chunk_index)
        if inner + EXFAT_FAT_ENTRY_SIZE > len(chunk):
            return 0
        return struct.unpack_from("<I", chunk, inner)[0]


def _read_chain(ctx: ProbeContext, boot: _Boot, fat: _FatTable, start: int) -> bytes:
    """Return the raw bytes of the cluster chain starting at *start*."""
    if start < EXFAT_FIRST_DATA_CLUSTER:
        return b""
    chunks: list[bytes] = []
    visited: set[int] = set()
    cluster = start
    total = 0
    while cluster >= EXFAT_FIRST_DATA_CLUSTER:
        if cluster in visited or len(visited) >= EXFAT_MAX_CHAIN_CLUSTERS:
            logger.debug("exfat: cluster chain loop at cluster %d", cluster)
            break
        visited.add(cluster)
        offset = (
            boot.cluster_heap_offset
            + (cluster - EXFAT_FIRST_DATA_CLUSTER) * boot.sectors_per_cluster
        ) * boot.bytes_per_sector
        try:
            data = ctx.read(offset, boot.cluster_size)
        except Exception:  # pragma: no cover - device level failure
            logger.debug("exfat: cluster %d unreadable", cluster, exc_info=True)
            break
        if not data:
            break
        chunks.append(data)
        total += len(data)
        if total >= EXFAT_MAX_DIRECTORY_BYTES:
            break
        cluster = fat.entry(cluster)
        if cluster == EXFAT_FAT_END_OF_CHAIN:
            break
    return b"".join(chunks)


def _decode_name(chunks: list[str], name_length: int) -> str:
    """Join the File Name Directory Entry fragments into a single name."""
    name = "".join(chunks)
    name = name.replace("\ufffd", "")
    name = name.rstrip("\x00\uffff")
    if name_length and len(name) > name_length:
        name = name[:name_length]
    return name


def _parse_file_set(chunk: bytes) -> DirEntry | None:
    """Decode one File Directory Entry set (primary + secondary entries)."""
    if len(chunk) < EXFAT_DIRECTORY_ENTRY_SIZE:
        return None
    try:
        attributes = struct.unpack_from("<H", chunk, EXFAT_FILE_OFF_ATTRIBUTES)[0]
        modified_raw = struct.unpack_from("<I", chunk, EXFAT_FILE_OFF_LAST_MODIFIED)[0]
        tenths = chunk[EXFAT_FILE_OFF_LAST_MODIFIED_10MS]
    except struct.error:
        return None

    first_cluster = 0
    data_length = 0
    name_length = 0
    name_parts: list[str] = []

    offset = EXFAT_DIRECTORY_ENTRY_SIZE
    while offset + EXFAT_DIRECTORY_ENTRY_SIZE <= len(chunk):
        entry = chunk[offset : offset + EXFAT_DIRECTORY_ENTRY_SIZE]
        entry_type = entry[0]
        if entry_type == EXFAT_ENTRY_STREAM_EXTENSION:
            try:
                name_length = entry[EXFAT_STREAM_OFF_NAME_LENGTH]
                first_cluster = struct.unpack_from(
                    "<I", entry, EXFAT_STREAM_OFF_FIRST_CLUSTER
                )[0]
                data_length = struct.unpack_from(
                    "<Q", entry, EXFAT_STREAM_OFF_DATA_LENGTH
                )[0]
            except struct.error:
                return None
        elif entry_type == EXFAT_ENTRY_FILE_NAME:
            raw = entry[EXFAT_NAME_OFF_FILE_NAME : EXFAT_NAME_OFF_FILE_NAME + 30]
            try:
                text = raw.decode("utf-16-le", errors="replace")
            except UnicodeDecodeError:  # pragma: no cover - defensive
                text = ""
            name_parts.append(text[:EXFAT_NAME_CHARS_PER_ENTRY])
        offset += EXFAT_DIRECTORY_ENTRY_SIZE

    name = _decode_name(name_parts, name_length)
    if not name or name in (".", ".."):
        return None

    is_dir = bool(attributes & EXFAT_ATTR_DIRECTORY)
    return DirEntry(
        name=name,
        is_dir=is_dir,
        size=0 if is_dir else data_length,
        modified=_dos_timestamp_to_epoch(modified_raw, tenths),
        inode=first_cluster or None,
        is_hidden=bool(attributes & EXFAT_ATTR_HIDDEN),
    )


def _parse_directory(data: bytes) -> list[DirEntry]:
    """Parse the directory entries contained in *data*."""
    entries: list[DirEntry] = []
    position = 0
    total = len(data)
    while position + EXFAT_DIRECTORY_ENTRY_SIZE <= total:
        entry_type = data[position]
        if entry_type == 0x00:
            # An unused entry marks the end of the directory.
            break
        if entry_type != EXFAT_ENTRY_FILE:
            # Volume label, allocation bitmap, up-case table and vendor
            # entries carry no user visible file.
            position += EXFAT_DIRECTORY_ENTRY_SIZE
            continue
        secondary_count = data[position + 1]
        set_size = EXFAT_DIRECTORY_ENTRY_SIZE * (1 + secondary_count)
        chunk = data[position : position + set_size]
        if len(chunk) < set_size:
            break
        entry = _parse_file_set(chunk)
        if entry is not None:
            entries.append(entry)
            if len(entries) >= EXFAT_MAX_DIRECTORY_ENTRIES:
                break
        position += set_size
    return entries


def _read_directory_cluster(
    ctx: ProbeContext, boot: _Boot, fat: _FatTable, cluster: int
) -> list[DirEntry]:
    """List the entries of the directory stored in *cluster*."""
    data = _read_chain(ctx, boot, fat, cluster)
    if not data:
        return []
    return _parse_directory(data)


def _read_volume_label(ctx: ProbeContext, boot: _Boot, fat: _FatTable) -> str:
    """Read the volume label from the root directory (entry type 0x83)."""
    data = _read_chain(ctx, boot, fat, boot.root_dir_cluster)
    position = 0
    total = len(data)
    while position + EXFAT_DIRECTORY_ENTRY_SIZE <= total:
        entry_type = data[position]
        if entry_type == 0x00:
            break
        if entry_type == EXFAT_ENTRY_VOLUME_LABEL:
            entry = data[position : position + EXFAT_DIRECTORY_ENTRY_SIZE]
            char_count = entry[1]
            raw = entry[2 : 2 + max(0, min(char_count, 15)) * 2]
            try:
                label = raw.decode("utf-16-le", errors="replace")
            except UnicodeDecodeError:  # pragma: no cover - defensive
                label = ""
            return label.rstrip("\x00\uffff")
        if entry_type == EXFAT_ENTRY_FILE:
            secondary_count = data[position + 1]
            position += EXFAT_DIRECTORY_ENTRY_SIZE * (1 + secondary_count)
            continue
        position += EXFAT_DIRECTORY_ENTRY_SIZE
    return ""


def detect(ctx: ProbeContext) -> ProbeResult | None:
    """Detect an exFAT volume at the start of the candidate.

    The volume is recognised by the ``EXFAT   `` file system name at offset
    3 and the 0x55AA boot signature at offset 510 (specification section
    3.1).  The remaining boot sector fields are validated and their state
    drives the confidence:

    * 1.0 -- every structural field is self consistent,
    * 0.9 -- one soft field is inconsistent (for example the volume claims to
      be larger than the remaining device),
    * 0.6 -- a hard field is invalid (sector or cluster geometry),
    * 0.3 -- more than one hard field is invalid.
    """
    boot = _read_boot(ctx)
    if boot is None:
        return None

    oem = boot[EXFAT_OFF_OEM : EXFAT_OFF_OEM + len(EXFAT_OEM_ID)]
    if oem != EXFAT_OEM_ID:
        return None
    if boot[EXFAT_OFF_BOOT_SIGNATURE : EXFAT_OFF_BOOT_SIGNATURE + 2] != EXFAT_BOOT_SIGNATURE:
        return None

    parsed = _parse_boot(boot)
    if parsed is None:
        return None

    evidence: list[str] = [f"OEM id {EXFAT_OEM_ID!r} present"]
    evidence.append("boot signature 0x55AA present")

    hard_problems: list[str] = []
    soft_problems: list[str] = []

    bytes_per_sector = parsed.bytes_per_sector
    sectors_per_cluster = parsed.sectors_per_cluster
    cluster_size = parsed.cluster_size

    if bytes_per_sector in (512, 1024, 2048, 4096):
        evidence.append(f"bytes_per_sector={bytes_per_sector} valid")
    else:
        hard_problems.append(f"bytes_per_sector={bytes_per_sector} invalid")

    if (
        sectors_per_cluster >= 1
        and cluster_size <= EXFAT_MAX_CLUSTER_SIZE
        and parsed.cluster_count <= EXFAT_MAX_CLUSTER_COUNT
    ):
        evidence.append(
            f"sectors_per_cluster={sectors_per_cluster} "
            f"(cluster size {cluster_size} bytes) valid"
        )
    else:
        hard_problems.append(
            f"sectors_per_cluster={sectors_per_cluster} invalid (cluster size {cluster_size})"
        )

    if parsed.number_of_fats == 1:
        evidence.append("number_of_fats=1 valid")
    else:
        hard_problems.append(f"number_of_fats={parsed.number_of_fats} invalid")

    volume_bytes = ctx.volume_bytes()
    if parsed.volume_length == 0:
        hard_problems.append("volume_length=0 invalid")
    elif parsed.volume_length * bytes_per_sector > volume_bytes:
        soft_problems.append(
            f"volume_length={parsed.volume_length} sectors exceeds the "
            f"{volume_bytes} bytes left on the device"
        )
    else:
        evidence.append(
            f"volume_length={parsed.volume_length} sectors fits in the device"
        )

    if parsed.fat_length == 0:
        hard_problems.append("fat_length=0 invalid")
    elif parsed.fat_offset + parsed.fat_length > parsed.volume_length:
        soft_problems.append(
            f"FAT region (sectors {parsed.fat_offset}.."
            f"{parsed.fat_offset + parsed.fat_length}) outside the volume"
        )
    else:
        evidence.append(
            f"FAT at sector {parsed.fat_offset} ({parsed.fat_length} sectors) inside volume"
        )

    if parsed.cluster_heap_offset >= parsed.volume_length:
        soft_problems.append(
            f"cluster_heap_offset={parsed.cluster_heap_offset} outside the volume"
        )
    else:
        heap_clusters = (
            parsed.volume_length - parsed.cluster_heap_offset
        ) // max(1, sectors_per_cluster)
        if parsed.cluster_count > heap_clusters:
            soft_problems.append(
                f"cluster_count={parsed.cluster_count} exceeds the {heap_clusters} "
                "clusters implied by the volume length"
            )
        else:
            evidence.append(
                f"cluster_count={parsed.cluster_count} within volume"
            )

    if parsed.root_dir_cluster == 0:
        soft_problems.append("root_dir_cluster=0 invalid")
    elif parsed.root_dir_cluster > parsed.cluster_count + 1:
        soft_problems.append(
            f"root_dir_cluster={parsed.root_dir_cluster} outside the cluster heap"
        )
    else:
        evidence.append(f"root_dir_cluster={parsed.root_dir_cluster} valid")

    label = ""
    if not hard_problems:
        try:
            fat = _FatTable(ctx, parsed)
            label = _read_volume_label(ctx, parsed, fat)
        except Exception:  # pragma: no cover - defensive
            logger.debug("exfat: volume label lookup failed", exc_info=True)

    if hard_problems:
        confidence = 0.6 if len(hard_problems) == 1 else 0.3
        evidence.extend(hard_problems)
    elif soft_problems:
        confidence = 0.9 if len(soft_problems) == 1 else 0.6
        evidence.extend(soft_problems)
    else:
        confidence = 1.0

    device_sectors = _to_device_sectors(
        parsed.volume_length, bytes_per_sector, ctx.sector_size
    )

    details: dict[str, object] = {
        "fs_type": FS_TYPE,
        "label": label,
        "bytes_per_sector": bytes_per_sector,
        "sectors_per_cluster": sectors_per_cluster,
        "cluster_size": cluster_size,
        "total_sectors": device_sectors,
        "volume_length": parsed.volume_length,
        "cluster_count": parsed.cluster_count,
        "volume_serial": parsed.volume_serial,
        "fat_offset": parsed.fat_offset,
        "fat_length": parsed.fat_length,
        "cluster_heap_offset": parsed.cluster_heap_offset,
        "root_dir_cluster": parsed.root_dir_cluster,
    }
    return ProbeResult(
        fs_type=FS_TYPE,
        label=label,
        confidence=confidence,
        details=details,
        evidence=tuple(evidence),
    )


def read_directory(
    ctx: ProbeContext, path: tuple[str, ...] = ()
) -> list[DirEntry]:
    """List the entries of a directory of the exFAT volume at the candidate.

    ``path`` is a tuple of directory names relative to the volume root.  The
    root directory is the cluster chain that starts at ``RootDirectoryCluster``
    of the boot sector; sub directories are reached through the first cluster
    of their Stream Extension Directory Entry.
    """
    try:
        boot = _read_boot(ctx)
        if boot is None:
            return []
        parsed = _parse_boot(boot)
        if parsed is None:
            return []
        if parsed.cluster_size <= 0 or parsed.bytes_per_sector <= 0:
            return []

        fat = _FatTable(ctx, parsed)
        cluster = parsed.root_dir_cluster
        for component in path:
            if not component:
                continue
            entries = _read_directory_cluster(ctx, parsed, fat, cluster)
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
            cluster = match.inode
        return _read_directory_cluster(ctx, parsed, fat, cluster)
    except Exception:  # pragma: no cover - defensive, corrupt volumes
        logger.warning("exfat: directory listing failed", exc_info=True)
        return []
