"""NTFS volume structures: boot sector, $MFT records, attributes and runlists.

The NTFS specifics implemented here are the ones needed to (a) recognise a
volume start and (b) prove where the volume actually ends:

* the volume boot sector (DBR) and its backup copy 16 sectors into the volume;
* $MFT record parsing, including the update sequence array fixups;
* attribute lookup by type, resident and non-resident;
* data run ("runlist") decoding;
* reading the $Bitmap meta-file, whose allocation bits are the ground truth
  used to confirm a partition boundary.

Reference: Microsoft [MS-FSCC] and the NTFS documentation published with the
Windows Driver Kit.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass, field
from typing import Iterator

from ..constants import (
    NTFS_BACKUP_VBR_SECTOR,
    NTFS_BITMAP_FILENAME,
    NTFS_BOOT_SECTOR_SIZE,
    NTFS_MFT_FILENAME,
    NTFS_OFF_BOOT_SIGNATURE,
    NTFS_OFF_BYTES_PER_SECTOR,
    NTFS_OFF_CLUSTER_PER_FILE_RECORD,
    NTFS_OFF_MFT_LCN,
    NTFS_OFF_MFTMIRR_LCN,
    NTFS_OFF_OEM,
    NTFS_OFF_SECTORS_PER_CLUSTER,
    NTFS_OFF_TOTAL_SECTORS,
    NTFS_OFF_VOLUME_SERIAL,
    NTFS_OEM_ID,
    VALID_BYTES_PER_SECTOR,
)
from .base import DirEntry, ProbeContext, ProbeResult

logger = logging.getLogger(__name__)

__all__ = [
    "FS_TYPE",
    "NtfsBootSector",
    "NtfsVolume",
    "detect",
    "read_directory",
]

FS_TYPE = "ntfs"

#: Well known MFT record numbers.
MFT_RECORD_MFT = 0
MFT_RECORD_MFTMIRR = 1
MFT_RECORD_LOGFILE = 2
MFT_RECORD_VOLUME = 3
MFT_RECORD_ROOT = 5
MFT_RECORD_BITMAP = 6

# Attribute type codes.
ATTR_STANDARD_INFORMATION = 0x10
ATTR_ATTRIBUTE_LIST = 0x20
ATTR_FILE_NAME = 0x30
ATTR_OBJECT_ID = 0x40
ATTR_VOLUME_NAME = 0x60
ATTR_VOLUME_INFORMATION = 0x70
ATTR_DATA = 0x80
ATTR_INDEX_ROOT = 0x90
ATTR_INDEX_ALLOCATION = 0xA0
ATTR_BITMAP = 0xB0
ATTR_REPARSE_POINT = 0xC0

#: Flags of an MFT record.
MFT_RECORD_IN_USE = 0x0001
MFT_RECORD_IS_DIRECTORY = 0x0002

#: Flags of a file name attribute.
FILE_ATTR_DIRECTORY = 0x10000000
FILE_ATTR_VIEW_INDEX_PRESENT = 0x0001


# --------------------------------------------------------------------------
# Boot sector
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NtfsBootSector:
    """Parsed NTFS volume boot sector."""

    bytes_per_sector: int
    sectors_per_cluster: int
    total_sectors: int
    mft_lcn: int
    mftmirr_lcn: int
    clusters_per_file_record: int
    volume_serial: int
    media_descriptor: int
    raw: bytes = field(repr=False, default=b"")

    @property
    def cluster_size(self) -> int:
        """Size of a cluster in bytes."""
        return self.bytes_per_sector * self.sectors_per_cluster

    @property
    def total_clusters(self) -> int:
        """Number of clusters addressable in the volume."""
        return self.total_sectors // self.sectors_per_cluster

    @property
    def file_record_size(self) -> int:
        """Size of a single MFT record in bytes.

        The boot sector stores the number of clusters per file record.  A
        negative value means the size is ``2 ** -value`` bytes.
        """
        if self.clusters_per_file_record > 0:
            return self.clusters_per_file_record * self.cluster_size
        if self.clusters_per_file_record < 0:
            return 1 << (-self.clusters_per_file_record)
        return 0


def parse_boot_sector(data: bytes) -> NtfsBootSector | None:
    """Parse an NTFS volume boot sector.

    Returns ``None`` when the sector does not carry the NTFS OEM identifier
    or when the BIOS parameter block is structurally impossible.
    """
    if len(data) < NTFS_BOOT_SECTOR_SIZE:
        return None
    if data[NTFS_OFF_OEM:NTFS_OFF_OEM + 8] != NTFS_OEM_ID:
        return None
    if data[NTFS_OFF_BOOT_SIGNATURE:NTFS_OFF_BOOT_SIGNATURE + 2] != b"\x55\xaa":
        return None

    bytes_per_sector = struct.unpack_from("<H", data, NTFS_OFF_BYTES_PER_SECTOR)[0]
    if bytes_per_sector not in VALID_BYTES_PER_SECTOR:
        return None

    sectors_per_cluster = data[NTFS_OFF_SECTORS_PER_CLUSTER]
    if sectors_per_cluster == 0 or sectors_per_cluster & (sectors_per_cluster - 1):
        return None
    if bytes_per_sector * sectors_per_cluster > 2 * 1024 * 1024:
        return None

    total_sectors = struct.unpack_from("<Q", data, NTFS_OFF_TOTAL_SECTORS)[0]
    if total_sectors == 0:
        return None

    mft_lcn = struct.unpack_from("<Q", data, NTFS_OFF_MFT_LCN)[0]
    mftmirr_lcn = struct.unpack_from("<Q", data, NTFS_OFF_MFTMIRR_LCN)[0]
    if mft_lcn == 0:
        return None

    raw_clusters = struct.unpack_from("<b", data, NTFS_OFF_CLUSTER_PER_FILE_RECORD)[0]

    volume_serial = struct.unpack_from("<Q", data, NTFS_OFF_VOLUME_SERIAL)[0]
    media = data[0x15]

    boot = NtfsBootSector(
        bytes_per_sector=bytes_per_sector,
        sectors_per_cluster=sectors_per_cluster,
        total_sectors=total_sectors,
        mft_lcn=mft_lcn,
        mftmirr_lcn=mftmirr_lcn,
        clusters_per_file_record=raw_clusters,
        volume_serial=volume_serial,
        media_descriptor=media,
        raw=data,
    )
    return boot


# --------------------------------------------------------------------------
# MFT records and attributes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Attribute:
    """One attribute of an MFT record."""

    type_code: int
    non_resident: bool
    name: str
    flags: int
    value: bytes | None
    runlist: tuple[tuple[int, int], ...]
    real_size: int
    allocated_size: int
    initialized_size: int

    @property
    def is_named(self) -> bool:
        return bool(self.name)


@dataclass(frozen=True)
class MftRecord:
    """A single MFT record."""

    record_number: int
    sequence_number: int
    flags: int
    attributes: tuple[Attribute, ...]

    @property
    def in_use(self) -> bool:
        return bool(self.flags & MFT_RECORD_IN_USE)

    @property
    def is_directory(self) -> bool:
        return bool(self.flags & MFT_RECORD_IS_DIRECTORY)

    def find(self, type_code: int, name: str | None = None) -> Attribute | None:
        """Return the first attribute of ``type_code`` (optionally named)."""
        for attr in self.attributes:
            if attr.type_code != type_code:
                continue
            if name is None or attr.name == name:
                return attr
        return None

    def find_all(self, type_code: int) -> list[Attribute]:
        return [a for a in self.attributes if a.type_code == type_code]


def apply_fixups(data: bytes, sector_size: int) -> bytes:
    """Undo the NTFS update sequence array protection.

    Every ``sector_size`` bytes of a record the last two bytes are replaced by
    the update sequence number.  The original values are stored in the update
    sequence array at the beginning of the record.
    """
    if len(data) < 0x30 or sector_size <= 0:
        return data
    usa_offset = struct.unpack_from("<H", data, 0x04)[0]
    usa_count = struct.unpack_from("<H", data, 0x06)[0]
    if usa_count < 1 or usa_offset + usa_count * 2 > len(data):
        return data
    usn = data[usa_offset:usa_offset + 2]
    buf = bytearray(data)
    for i in range(1, usa_count):
        pos = i * sector_size - 2
        if pos + 2 > len(buf):
            break
        if bytes(buf[pos:pos + 2]) != usn:
            # The record was not written with fixups applied; treat as corrupt.
            return data
        buf[pos:pos + 2] = data[usa_offset + i * 2:usa_offset + i * 2 + 2]
    return bytes(buf)


def decode_runlist(data: bytes) -> tuple[tuple[int, int], ...]:
    """Decode an NTFS data run list.

    Returns a tuple of ``(length_clusters, lcn)`` pairs.  ``lcn`` is the
    absolute cluster number; sparse runs use ``lcn = -1``.
    """
    runs: list[tuple[int, int]] = []
    offset = 0
    lcn = 0
    size = len(data)
    while offset < size:
        header = data[offset]
        if header == 0:
            break
        length_size = header & 0x0F
        offset_size = (header >> 4) & 0x0F
        offset += 1
        if length_size == 0 or offset + length_size + offset_size > size:
            break
        length = int.from_bytes(data[offset:offset + length_size], "little", signed=False)
        offset += length_size
        if offset_size == 0:
            runs.append((length, -1))  # sparse run
            continue
        delta = int.from_bytes(data[offset:offset + offset_size], "little", signed=True)
        offset += offset_size
        lcn += delta
        runs.append((length, lcn))
    return tuple(runs)


def parse_attributes(record: bytes) -> tuple[Attribute, ...]:
    """Parse the attribute list of an MFT record."""
    attrs: list[Attribute] = []
    if len(record) < 0x18:
        return ()
    attr_offset = struct.unpack_from("<H", record, 0x14)[0]
    if attr_offset < 0x18 or attr_offset >= len(record):
        return ()
    pos = attr_offset
    while pos + 4 <= len(record):
        type_code = struct.unpack_from("<I", record, pos)[0]
        if type_code == 0xFFFFFFFF:
            break
        if pos + 16 > len(record):
            break
        length = struct.unpack_from("<I", record, pos + 4)[0]
        if length < 16 or pos + length > len(record):
            break
        non_resident = record[pos + 8]
        name_length = record[pos + 9]
        name_offset = struct.unpack_from("<H", record, pos + 10)[0]
        flags = struct.unpack_from("<H", record, pos + 12)[0]
        name = ""
        if name_length:
            npos = pos + name_offset
            if npos + name_length * 2 <= len(record):
                name = record[npos:npos + name_length * 2].decode("utf-16-le", "ignore")
        if non_resident:
            if pos + 0x40 > len(record):
                pos += length
                continue
            runlist_offset = struct.unpack_from("<H", record, pos + 0x20)[0]
            allocated = struct.unpack_from("<Q", record, pos + 0x28)[0]
            real = struct.unpack_from("<Q", record, pos + 0x30)[0]
            initialized = struct.unpack_from("<Q", record, pos + 0x38)[0]
            runlist = decode_runlist(record[pos + runlist_offset:pos + length]) if runlist_offset else ()
            attrs.append(
                Attribute(
                    type_code=type_code,
                    non_resident=True,
                    name=name,
                    flags=flags,
                    value=None,
                    runlist=runlist,
                    real_size=real,
                    allocated_size=allocated,
                    initialized_size=initialized,
                )
            )
        else:
            value_length = struct.unpack_from("<I", record, pos + 0x10)[0]
            value_offset = struct.unpack_from("<H", record, pos + 0x14)[0]
            value = b""
            if value_length and value_offset:
                vpos = pos + value_offset
                if vpos + value_length <= len(record):
                    value = record[vpos:vpos + value_length]
            attrs.append(
                Attribute(
                    type_code=type_code,
                    non_resident=False,
                    name=name,
                    flags=flags,
                    value=value,
                    runlist=(),
                    real_size=value_length,
                    allocated_size=value_length,
                    initialized_size=value_length,
                )
            )
        pos += length
    return tuple(attrs)


def parse_mft_record(data: bytes, sector_size: int) -> MftRecord | None:
    """Parse a single MFT record, applying the update sequence fixups."""
    if len(data) < 0x30:
        return None
    if data[:4] != b"FILE":
        return None
    fixed = apply_fixups(data, sector_size)
    flags = struct.unpack_from("<H", fixed, 0x16)[0]
    sequence = struct.unpack_from("<H", fixed, 0x10)[0]
    record_number = struct.unpack_from("<I", fixed, 0x2C)[0]
    attrs = parse_attributes(fixed)
    return MftRecord(
        record_number=record_number,
        sequence_number=sequence,
        flags=flags,
        attributes=attrs,
    )


# --------------------------------------------------------------------------
# Volume access
# --------------------------------------------------------------------------


class NtfsVolume:
    """Read-only accessor for an NTFS volume starting at a given sector."""

    def __init__(self, ctx: ProbeContext, boot: NtfsBootSector) -> None:
        self.ctx = ctx
        self.boot = boot
        self._mft_runs: tuple[tuple[int, int], ...] | None = None

    # -- low level ------------------------------------------------------
    def _volume_offset(self, lcn: int, cluster_count: int = 1) -> int:
        """Byte offset of a cluster relative to the volume start."""
        return lcn * self.boot.cluster_size

    def read_cluster(self, lcn: int) -> bytes:
        """Read one cluster of the volume."""
        size = self.boot.cluster_size
        offset = self.ctx.byte_offset + self._volume_offset(lcn)
        return self.ctx.device.read_at(offset, size)

    def read_runs(self, runs: tuple[tuple[int, int], ...], size: int) -> bytes:
        """Read ``size`` bytes following a runlist."""
        out = bytearray()
        for length, lcn in runs:
            if lcn < 0:
                out.extend(b"\x00" * (length * self.boot.cluster_size))
                if len(out) >= size:
                    break
                continue
            for i in range(length):
                out.extend(self.read_cluster(lcn + i))
                if len(out) >= size:
                    return bytes(out[:size])
        return bytes(out[:size])

    # -- MFT ------------------------------------------------------------
    @property
    def mft_runs(self) -> tuple[tuple[int, int], ...]:
        """Runlist of the ``$MFT`` meta-file.

        The first MFT record lives at the cluster the boot sector points at,
        so it can be read without knowing the runlist yet.
        """
        if self._mft_runs is None:
            size = self.boot.file_record_size
            if size <= 0:
                self._mft_runs = ()
                return self._mft_runs
            try:
                data = self.ctx.device.read_at(
                    self.ctx.byte_offset + self.boot.mft_lcn * self.boot.cluster_size, size
                )
            except Exception:  # pragma: no cover - defensive
                self._mft_runs = ()
                return self._mft_runs
            record = parse_mft_record(data, self.boot.bytes_per_sector)
            data_attr = record.find(ATTR_DATA) if record else None
            self._mft_runs = data_attr.runlist if data_attr else ()
        return self._mft_runs

    def read_mft_record(self, number: int) -> MftRecord | None:
        """Read and parse the MFT record with the given number."""
        runs = self.mft_runs
        if not runs:
            return None
        size = self.boot.file_record_size
        offset = number * size
        cluster_size = self.boot.cluster_size
        chunk = bytearray()
        for length, lcn in runs:
            if lcn < 0:
                continue
            run_bytes = length * cluster_size
            if offset >= run_bytes:
                offset -= run_bytes
                continue
            needed = min(run_bytes - offset, size)
            cluster_index = offset // cluster_size
            within = offset % cluster_size
            data = self.read_cluster(lcn + cluster_index)
            chunk.extend(data[within:within + needed])
            if len(chunk) >= size:
                break
            offset = 0
        if len(chunk) < size:
            return None
        return parse_mft_record(bytes(chunk), self.boot.bytes_per_sector)

    def iter_mft_records(self, limit: int = 4096) -> Iterator[MftRecord]:
        """Iterate over the first ``limit`` MFT records."""
        for number in range(limit):
            record = self.read_mft_record(number)
            if record is None:
                continue
            yield record

    def mft_record_count(self) -> int:
        """Number of MFT records declared by the $MFT data attribute."""
        record = self.read_mft_record(MFT_RECORD_MFT)
        if record is None:
            return 0
        data_attr = record.find(ATTR_DATA)
        if data_attr is None:
            return 0
        return data_attr.real_size // max(1, self.boot.file_record_size)

    # -- meta files -----------------------------------------------------
    def read_bitmap(self, max_bytes: int = 64 * 1024 * 1024) -> bytes | None:
        """Read the content of the ``$Bitmap`` meta-file.

        The bitmap holds one bit per cluster: ``1`` means the cluster is
        allocated to a file, ``0`` means it is free.
        """
        record = self.read_mft_record(MFT_RECORD_BITMAP)
        if record is None:
            return None
        attr = record.find(ATTR_DATA)
        if attr is None:
            return None
        if attr.non_resident:
            size = min(attr.real_size, max_bytes)
            if size <= 0:
                return None
            return self.read_runs(attr.runlist, size)
        return attr.value[:max_bytes] if attr.value else None

    def volume_serial(self) -> int:
        return self.boot.volume_serial

    def volume_name(self) -> str:
        """Read the volume label from the ``$VolumeName`` attribute."""
        record = self.read_mft_record(MFT_RECORD_VOLUME)
        if record is None:
            return ""
        attr = record.find(ATTR_VOLUME_NAME)
        if attr is None or not attr.value:
            return ""
        try:
            return attr.value.decode("utf-16-le").rstrip("\x00")
        except UnicodeDecodeError:  # pragma: no cover - defensive
            return ""

    def mft_present(self) -> bool:
        """True when the ``$MFT`` record can be read back."""
        record = self.read_mft_record(MFT_RECORD_MFT)
        return record is not None and record.find(ATTR_DATA) is not None


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------


def detect(ctx: ProbeContext) -> ProbeResult | None:
    """Detect an NTFS volume at the candidate start.

    The primary boot sector is validated first; when it is unusable the
    backup boot sector 16 sectors into the volume is tried as well.
    """
    evidence: list[str] = []
    try:
        primary = ctx.read(0, NTFS_BOOT_SECTOR_SIZE)
    except Exception as exc:  # pragma: no cover - device errors bubble up
        logger.debug("ntfs: primary boot sector unreadable: %s", exc)
        primary = b""

    boot = parse_boot_sector(primary)
    source = "primary"
    if boot is None:
        # The backup boot sector lives 16 sectors into the volume.
        backup_offset = NTFS_BACKUP_VBR_SECTOR * ctx.sector_size
        try:
            backup = ctx.read(backup_offset, NTFS_BOOT_SECTOR_SIZE)
        except Exception:  # pragma: no cover - defensive
            backup = b""
        boot = parse_boot_sector(backup)
        source = "backup"
        if boot is None:
            return None
        evidence.append("valid NTFS boot sector found in the backup copy")

    evidence.insert(0, "NTFS OEM identifier present")
    evidence.append(f"bytes_per_sector={boot.bytes_per_sector} (power of two, valid)")
    evidence.append(f"sectors_per_cluster={boot.sectors_per_cluster}")
    evidence.append(f"total_sectors={boot.total_sectors}")

    confidence = 0.95 if source == "primary" else 0.8

    # The backup boot sector must sit 16 sectors into the volume, and the
    # media descriptor should be 0xF8 for a fixed disk.
    if boot.media_descriptor not in (0xF8, 0xF0, 0xF9):
        confidence -= 0.1
        evidence.append(f"unusual media descriptor 0x{boot.media_descriptor:02X}")
    if boot.total_sectors * boot.bytes_per_sector > ctx.volume_bytes():
        confidence -= 0.15
        evidence.append("declared volume size exceeds the space available on the device")

    volume = NtfsVolume(ctx, boot)
    if volume.mft_present():
        evidence.append("$MFT record 0 is readable")
        confidence = min(1.0, confidence + 0.05)
    else:
        evidence.append("$MFT record 0 could not be read")
        confidence -= 0.25

    device_sectors = boot.total_sectors * boot.bytes_per_sector // ctx.sector_size

    return ProbeResult(
        fs_type=FS_TYPE,
        label="NTFS",
        confidence=max(0.0, min(1.0, confidence)),
        details={
            "bytes_per_sector": boot.bytes_per_sector,
            "sectors_per_cluster": boot.sectors_per_cluster,
            "cluster_size": boot.cluster_size,
            "total_sectors": device_sectors,
            "total_sectors_fs": boot.total_sectors,
            "mft_lcn": boot.mft_lcn,
            "volume_serial": boot.volume_serial,
            "volume_label": volume.volume_name(),
            "boot_sector_source": source,
        },
        evidence=tuple(evidence),
    )


# --------------------------------------------------------------------------
# Directory browsing
# --------------------------------------------------------------------------


def _file_name_entries(record: MftRecord) -> list[tuple[str, int, bool, int]]:
    """Extract ``(name, parent_reference, is_dir, size)`` from a record."""
    out: list[tuple[str, int, bool, int]] = []
    for attr in record.find_all(ATTR_FILE_NAME):
        if not attr.value or len(attr.value) < 0x42:
            continue
        value = attr.value
        parent_ref = struct.unpack_from("<Q", value, 0)[0] & 0x0000FFFFFFFFFFFF
        name_length = value[0x40]
        namespace = value[0x41]
        if 0x42 + name_length * 2 > len(value):
            continue
        try:
            name = value[0x42:0x42 + name_length * 2].decode("utf-16-le")
        except UnicodeDecodeError:
            continue
        real_size = struct.unpack_from("<Q", value, 0x30)[0]
        flags = struct.unpack_from("<I", value, 0x38)[0]
        is_dir = bool(flags & FILE_ATTR_DIRECTORY)
        out.append((name, parent_ref, is_dir, real_size))
    return out


def _data_size(record: MftRecord) -> int:
    """Total size of the unnamed $DATA attribute of a record."""
    attr = record.find(ATTR_DATA)
    if attr is None:
        return 0
    return attr.real_size


def _list_directory(volume: NtfsVolume, mft_number: int) -> list[DirEntry]:
    """List the children of the directory with the given MFT reference."""
    record = volume.read_mft_record(mft_number)
    if record is None:
        return []
    children: list[DirEntry] = []
    for attr in record.find_all(ATTR_FILE_NAME):
        if not attr.value or len(attr.value) < 0x42:
            continue
        value = attr.value
        parent_ref = struct.unpack_from("<Q", value, 0)[0] & 0x0000FFFFFFFFFFFF
        if parent_ref != mft_number:
            continue
        name_length = value[0x40]
        if 0x42 + name_length * 2 > len(value):
            continue
        try:
            name = value[0x42:0x42 + name_length * 2].decode("utf-16-le")
        except UnicodeDecodeError:
            continue
        flags = struct.unpack_from("<I", value, 0x38)[0]
        is_dir = bool(flags & FILE_ATTR_DIRECTORY)
        real_size = struct.unpack_from("<Q", value, 0x30)[0]
        modified = struct.unpack_from("<Q", value, 0x08)[0]
        modified_ts = modified / 10_000_000 - 116_444_736_00 if modified else None
        children.append(
            DirEntry(
                name=name,
                is_dir=is_dir,
                size=0 if is_dir else real_size,
                modified=modified_ts,
                inode=parent_ref,
                is_hidden=bool(flags & 0x00000004),
            )
        )
    return children


def _resolve_path(volume: NtfsVolume, path: tuple[str, ...]) -> int | None:
    """Resolve a path tuple to an MFT record number."""
    current = MFT_RECORD_ROOT
    for part in path:
        if not part or part in (".", ".."):
            continue
        found = None
        for entry in _list_directory(volume, current):
            if entry.name.lower() == part.lower():
                found = entry
                break
        if found is None:
            return None
        current = found.inode or 0
    return current


def read_directory(ctx: ProbeContext, path: tuple[str, ...] = ()) -> list[DirEntry]:
    """List the entries of an NTFS directory.

    ``path`` is a tuple of directory names relative to the volume root.
    Returns an empty list when the path does not exist or cannot be parsed.
    """
    try:
        primary = ctx.read(0, NTFS_BOOT_SECTOR_SIZE)
    except Exception:  # pragma: no cover - defensive
        return []
    boot = parse_boot_sector(primary)
    if boot is None:
        try:
            boot = parse_boot_sector(ctx.read(NTFS_BACKUP_VBR_SECTOR * ctx.sector_size,
                                             NTFS_BOOT_SECTOR_SIZE))
        except Exception:  # pragma: no cover - defensive
            return []
    if boot is None:
        return []

    volume = NtfsVolume(ctx, boot)
    target = _resolve_path(volume, path)
    if target is None:
        return []
    entries = _list_directory(volume, target)
    # The inode field of a child entry currently carries the parent reference
    # because that is what the $FILE_NAME attribute stores; resolve the real
    # child reference from the attribute list instead.
    resolved: list[DirEntry] = []
    record = volume.read_mft_record(target)
    for attr in (record.find_all(ATTR_FILE_NAME) if record else []):
        if not attr.value or len(attr.value) < 0x42:
            continue
        value = attr.value
        parent_ref = struct.unpack_from("<Q", value, 0)[0] & 0x0000FFFFFFFFFFFF
        if parent_ref != target:
            continue
        name_length = value[0x40]
        if 0x42 + name_length * 2 > len(value):
            continue
        try:
            name = value[0x42:0x42 + name_length * 2].decode("utf-16-le")
        except UnicodeDecodeError:
            continue
        flags = struct.unpack_from("<I", value, 0x38)[0]
        real_size = struct.unpack_from("<Q", value, 0x30)[0]
        modified = struct.unpack_from("<Q", value, 0x08)[0]
        modified_ts = (modified / 10_000_000 - 116_444_736_000) if modified else None
        resolved.append(
            DirEntry(
                name=name,
                is_dir=bool(flags & FILE_ATTR_DIRECTORY),
                size=0 if flags & FILE_ATTR_DIRECTORY else real_size,
                modified=modified_ts,
                inode=0,
                is_hidden=bool(flags & 0x00000004),
            )
        )
    return resolved or entries
