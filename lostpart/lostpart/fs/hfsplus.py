"""HFS Plus (HFS+) probe and read-only directory browser.

The on-disk structures implemented here are described by Apple Technical Note
TN1150 "HFS Plus Volume Format": the volume header, the ``HFSPlusForkData``
extents, the B-tree node structure and the catalog file records.

Every multi byte integer of an HFS Plus volume is stored **big endian**
(TN1150, "Basic Data Types").

The catalog B-tree reader implemented below walks the chain of leaf nodes
(``fLink``) instead of descending through the index nodes.  The chain is
documented in TN1150 and yields the catalog records in ascending key order
(parent CNID first, then the Unicode name), which is exactly what a
directory listing needs.  The price is that a directory that sits late in the
catalog costs one scan of the leaf chain; the number of visited nodes is
capped.
"""

from __future__ import annotations

import logging
import struct
import unicodedata
from dataclasses import dataclass
from typing import Final

from ..constants import (
    HFSPLUS_BLOCK_SIZE_OFFSET,
    HFSPLUS_MAGIC,
    HFSPLUS_MAGIC_OFFSET,
    HFSPLUS_SIGNATURE,
    HFSPLUS_SIGNATURE_OFFSET,
    HFSPLUS_TOTAL_BLOCKS_OFFSET,
    HFSPLUS_VERSION_4,
    HFSPLUS_VERSION_5,
    HFSPLUS_VERSION_OFFSET,
)
from .base import DirEntry, ProbeContext, ProbeResult

logger = logging.getLogger(__name__)

#: Identifier reported by the registry for this module.
FS_TYPE: Final = "hfsplus"

# --------------------------------------------------------------------------
# On-disk constants (TN1150)
# --------------------------------------------------------------------------

#: Offset of the ``version`` field inside the volume header.  TN1150 lays the
#: header out as ``signature`` (2 bytes) followed by ``version`` (2 bytes),
#: so the version sits at byte 2 of the header (absolute offset 1026).  The
#: project constant ``HFSPLUS_VERSION_OFFSET`` (1025) points at the *last
#: byte of the signature*, so it is only used as a fallback.
HFSPLUS_VERSION_FIELD_OFFSET: Final = 2
#: Legal allocation block sizes.
HFSPLUS_MIN_BLOCK_SIZE: Final = 512
HFSPLUS_MAX_BLOCK_SIZE: Final = 1048576
#: Signature of an HFSX (case sensitive) volume -- *not* HFS Plus.
HFSX_SIGNATURE: Final = b"HX"
#: Offset of the ``catalogFile`` fork inside the volume header.
HFSPLUS_CATALOG_FILE_OFFSET: Final = 1024 + 272
#: Offsets inside ``HFSPlusForkData``.
HFSPLUS_FORK_OFF_LOGICAL_SIZE: Final = 0
HFSPLUS_FORK_OFF_CLUMP_SIZE: Final = 8
HFSPLUS_FORK_OFF_TOTAL_BLOCKS: Final = 12
HFSPLUS_FORK_OFF_EXTENTS: Final = 16
#: Number of extents stored in the volume header.
HFSPLUS_EXTENT_COUNT: Final = 8

#: Size of a ``BTNodeDescriptor``.
HFSPLUS_BT_NODE_DESCRIPTOR_SIZE: Final = 14
#: Node kinds of a B-tree.
HFSPLUS_BT_KIND_INDEX: Final = 0
HFSPLUS_BT_KIND_HEADER: Final = 1
HFSPLUS_BT_KIND_LEAF: Final = -1
#: Legal B-tree node sizes.
HFSPLUS_BT_MIN_NODE_SIZE: Final = 512
HFSPLUS_BT_MAX_NODE_SIZE: Final = 32768

#: Offsets inside the B-tree header record (relative to the record start).
HFSPLUS_BT_OFF_TREE_DEPTH: Final = 0
HFSPLUS_BT_OFF_ROOT_NODE: Final = 2
HFSPLUS_BT_OFF_LEAF_RECORDS: Final = 6
HFSPLUS_BT_OFF_FIRST_LEAF_NODE: Final = 10
HFSPLUS_BT_OFF_LAST_LEAF_NODE: Final = 14
HFSPLUS_BT_OFF_NODE_SIZE: Final = 18
HFSPLUS_BT_OFF_MAX_KEY_LENGTH: Final = 20
HFSPLUS_BT_OFF_TOTAL_NODES: Final = 22

#: Catalog record types.
HFSPLUS_CATALOG_FOLDER_RECORD: Final = 0x0001
HFSPLUS_CATALOG_FILE_RECORD: Final = 0x0002
HFSPLUS_CATALOG_FOLDER_THREAD_RECORD: Final = 0x0003
HFSPLUS_CATALOG_FILE_THREAD_RECORD: Final = 0x0004

#: Offsets inside a catalog folder / file record.
HFSPLUS_CATALOG_OFF_RECORD_TYPE: Final = 0
HFSPLUS_CATALOG_OFF_FLAGS: Final = 2
HFSPLUS_CATALOG_OFF_CNID: Final = 8
HFSPLUS_CATALOG_OFF_MOD_DATE: Final = 16
#: Offset of the data fork inside a catalog file record.
HFSPLUS_CATALOG_FILE_OFF_DATA_FORK: Final = 88
#: Size of a catalog folder / file record.
HFSPLUS_CATALOG_FOLDER_RECORD_SIZE: Final = 88
HFSPLUS_CATALOG_FILE_RECORD_SIZE: Final = 248

#: The ``kIsInvisible`` flag of a catalog record.
HFSPLUS_FLAG_INVISIBLE: Final = 0x4000
#: CNID of the root folder.
HFSPLUS_ROOT_FOLDER_ID: Final = 2
#: Seconds between the HFS epoch (1904-01-01) and the Unix epoch.
HFSPLUS_EPOCH_OFFSET: Final = 2082844800

#: Safety limits for the catalog reader.
HFSPLUS_MAX_LEAF_NODES: Final = 1 << 16
HFSPLUS_MAX_RECORDS: Final = 1 << 20


def _u16(buf: bytes, off: int) -> int | None:
    """Return the big endian ``u16`` at ``off`` or ``None`` if truncated."""
    if off < 0 or off + 2 > len(buf):
        return None
    return struct.unpack_from(">H", buf, off)[0]


def _u32(buf: bytes, off: int) -> int | None:
    """Return the big endian ``u32`` at ``off`` or ``None`` if truncated."""
    if off < 0 or off + 4 > len(buf):
        return None
    return struct.unpack_from(">I", buf, off)[0]


def _u64(buf: bytes, off: int) -> int | None:
    """Return the big endian ``u64`` at ``off`` or ``None`` if truncated."""
    if off < 0 or off + 8 > len(buf):
        return None
    return struct.unpack_from(">Q", buf, off)[0]


def _is_power_of_two(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0


# --------------------------------------------------------------------------
# Volume header
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _VolumeHeader:
    """The fields of ``HFSPlusVolumeHeader`` this module needs."""

    signature: bytes
    version: int
    attributes: int
    file_count: int
    folder_count: int
    block_size: int
    total_blocks: int
    free_blocks: int
    next_catalog_id: int
    catalog_logical_size: int
    catalog_extents: tuple[tuple[int, int], ...]


def _read_volume_header(ctx: ProbeContext) -> _VolumeHeader | None:
    """Parse the volume header of the candidate volume.

    ``None`` is returned when the structure is not an HFS Plus volume header
    (wrong signature, unknown version, impossible geometry).
    """
    size = HFSPLUS_MAGIC_OFFSET + 4 - HFSPLUS_SIGNATURE_OFFSET
    try:
        raw = ctx.read(HFSPLUS_SIGNATURE_OFFSET, size)
    except Exception:  # pragma: no cover - device error
        logger.debug("hfsplus: cannot read the volume header", exc_info=True)
        return None
    if len(raw) < size:
        return None

    signature = raw[0:2]
    if signature != HFSPLUS_SIGNATURE:
        return None

    version = _u16(raw, HFSPLUS_VERSION_FIELD_OFFSET)
    if version not in (HFSPLUS_VERSION_4, HFSPLUS_VERSION_5):
        # Fall back to the offset used by the project constants.
        fallback = _u16(raw, HFSPLUS_VERSION_OFFSET - HFSPLUS_SIGNATURE_OFFSET)
        if fallback in (HFSPLUS_VERSION_4, HFSPLUS_VERSION_5):
            version = fallback
    if version is None or version not in (HFSPLUS_VERSION_4, HFSPLUS_VERSION_5):
        return None

    attributes = _u32(raw, 4)
    file_count = _u32(raw, 32)
    folder_count = _u32(raw, 36)
    block_size = _u32(raw, HFSPLUS_BLOCK_SIZE_OFFSET - HFSPLUS_SIGNATURE_OFFSET)
    total_blocks = _u32(raw, HFSPLUS_TOTAL_BLOCKS_OFFSET - HFSPLUS_SIGNATURE_OFFSET)
    free_blocks = _u32(raw, 48)
    next_catalog_id = _u32(raw, 64)
    if None in (
        attributes,
        file_count,
        folder_count,
        block_size,
        total_blocks,
        free_blocks,
        next_catalog_id,
    ):
        return None

    if not _is_power_of_two(block_size):
        return None
    if block_size < HFSPLUS_MIN_BLOCK_SIZE or block_size > HFSPLUS_MAX_BLOCK_SIZE:
        return None
    if total_blocks <= 0:
        return None
    if total_blocks * block_size > ctx.volume_bytes():
        return None

    fork_offset = HFSPLUS_CATALOG_FILE_OFFSET - HFSPLUS_SIGNATURE_OFFSET
    logical_size = _u64(raw, fork_offset + HFSPLUS_FORK_OFF_LOGICAL_SIZE)
    if logical_size is None:
        return None
    extents: list[tuple[int, int]] = []
    for i in range(HFSPLUS_EXTENT_COUNT):
        base = fork_offset + HFSPLUS_FORK_OFF_EXTENTS + i * 8
        start = _u32(raw, base)
        count = _u32(raw, base + 4)
        if start is None or count is None:
            break
        if count:
            extents.append((start, count))

    return _VolumeHeader(
        signature=signature,
        version=version,
        attributes=attributes,
        file_count=file_count,
        folder_count=folder_count,
        block_size=block_size,
        total_blocks=total_blocks,
        free_blocks=free_blocks,
        next_catalog_id=next_catalog_id,
        catalog_logical_size=logical_size,
        catalog_extents=tuple(extents),
    )


def detect(ctx: ProbeContext) -> ProbeResult | None:
    """Detect an HFS Plus volume at the start of a candidate volume.

    The volume header lives 1024 bytes into the volume.  Its signature must
    be ``H+``; the classic HFS wrapper signature ``HX`` (HFSX) is rejected.
    The confidence ladder is:

    ============================================  =======
    Evidence                                      Weight
    ============================================  =======
    signature ``H+`` and version 4 or 5           +0.55
    volume magic ``0x482B``                       +0.45
    ============================================  =======

    A volume whose signature and version are correct but whose magic is
    missing or wrong is reported with a confidence of 0.6; a volume that
    fails any structural check (impossible block size, block count larger
    than the candidate volume, unknown version) is rejected with ``None``.
    """
    header = _read_volume_header(ctx)
    if header is None:
        return None

    try:
        raw = ctx.read(HFSPLUS_MAGIC_OFFSET, 4)
    except Exception:  # pragma: no cover - device error
        logger.debug("hfsplus: cannot read the volume magic", exc_info=True)
        return None

    magic = _u32(raw, 0)
    evidence = [
        f"volume header signature {HFSPLUS_SIGNATURE!r} at offset "
        f"{HFSPLUS_SIGNATURE_OFFSET}",
        f"volume header version {header.version}",
        f"allocation block size {header.block_size} bytes, {header.total_blocks} blocks",
    ]

    if magic == HFSPLUS_MAGIC:
        evidence.append(f"volume magic 0x{HFSPLUS_MAGIC:04X}")
        confidence = 1.0
    else:
        evidence.append(
            f"volume magic is 0x{magic:04X}, expected 0x{HFSPLUS_MAGIC:04X}" if magic
            is not None else "volume magic is missing"
        )
        confidence = 0.6

    details: dict[str, object] = {
        "version": header.version,
        "signature": header.signature.decode("ascii", errors="replace"),
        "block_size": header.block_size,
        "total_blocks": header.total_blocks,
        "free_blocks": header.free_blocks,
        "file_count": header.file_count,
        "folder_count": header.folder_count,
        "next_catalog_id": header.next_catalog_id,
        "attributes": header.attributes,
        "catalog_logical_size": header.catalog_logical_size,
        "bytes_per_sector": ctx.sector_size,
    }
    total_bytes = header.total_blocks * header.block_size
    details["total_sectors"] = total_bytes // ctx.sector_size
    if header.block_size >= ctx.sector_size:
        details["sectors_per_cluster"] = header.block_size // ctx.sector_size

    return ProbeResult(
        fs_type=FS_TYPE,
        label="HFS Plus",
        confidence=confidence,
        details=details,
        evidence=tuple(evidence),
    )


# --------------------------------------------------------------------------
# Catalog B-tree
# --------------------------------------------------------------------------


class _ForkReader:
    """Reads bytes out of an HFS Plus fork described by its extents."""

    def __init__(
        self,
        extents: tuple[tuple[int, int], ...],
        block_size: int,
        logical_size: int,
    ) -> None:
        self.block_size = block_size
        self.logical_size = logical_size
        self._segments: list[tuple[int, int, int]] = []
        position = 0
        for start_block, block_count in extents:
            length = block_count * block_size
            self._segments.append((position, start_block * block_size, length))
            position += length

    def read(self, ctx: ProbeContext, offset: int, size: int) -> bytes:
        """Read ``size`` bytes at ``offset`` inside the fork."""
        out = bytearray()
        position = offset
        remaining = size
        while remaining > 0:
            segment = self._segment(position)
            if segment is None:
                break
            fork_start, volume_start, length = segment
            inside = position - fork_start
            take = min(remaining, length - inside)
            if take <= 0:
                break
            try:
                data = ctx.read(volume_start + inside, take)
            except Exception:  # pragma: no cover - device error
                logger.debug("hfsplus: cannot read fork data", exc_info=True)
                break
            if len(data) < take:
                out.extend(data)
                break
            out.extend(data)
            position += take
            remaining -= take
        return bytes(out)

    def _segment(self, position: int) -> tuple[int, int, int] | None:
        for fork_start, volume_start, length in self._segments:
            if fork_start <= position < fork_start + length:
                return (fork_start, volume_start, length)
        return None


@dataclass(frozen=True)
class _BTreeHeader:
    """The header record of the catalog B-tree."""

    tree_depth: int
    root_node: int
    leaf_records: int
    first_leaf_node: int
    last_leaf_node: int
    node_size: int
    total_nodes: int


def _read_btree_header(node: bytes) -> _BTreeHeader | None:
    """Parse the ``BTHeaderRec`` stored in the first record of node 0."""
    base = HFSPLUS_BT_NODE_DESCRIPTOR_SIZE
    tree_depth = _u16(node, base + HFSPLUS_BT_OFF_TREE_DEPTH)
    root_node = _u32(node, base + HFSPLUS_BT_OFF_ROOT_NODE)
    leaf_records = _u32(node, base + HFSPLUS_BT_OFF_LEAF_RECORDS)
    first_leaf_node = _u32(node, base + HFSPLUS_BT_OFF_FIRST_LEAF_NODE)
    last_leaf_node = _u32(node, base + HFSPLUS_BT_OFF_LAST_LEAF_NODE)
    node_size = _u16(node, base + HFSPLUS_BT_OFF_NODE_SIZE)
    total_nodes = _u32(node, base + HFSPLUS_BT_OFF_TOTAL_NODES)
    if None in (
        tree_depth,
        root_node,
        leaf_records,
        first_leaf_node,
        last_leaf_node,
        node_size,
        total_nodes,
    ):
        return None
    return _BTreeHeader(
        tree_depth=tree_depth,
        root_node=root_node,
        leaf_records=leaf_records,
        first_leaf_node=first_leaf_node,
        last_leaf_node=last_leaf_node,
        node_size=node_size,
        total_nodes=total_nodes,
    )


def _record_ranges(node: bytes, num_records: int) -> list[tuple[int, int]]:
    """Return the ``(start, end)`` byte range of every record of a node.

    The list of record offsets lives in the last ``2 * (numRecords + 1)``
    bytes of the node and is stored in reverse order (TN1150, "Node
    Structure").  The extra entry points at the first byte of free space and
    therefore marks the end of the last record.
    """
    node_size = len(node)
    array_start = node_size - 2 * (num_records + 1)
    if array_start < HFSPLUS_BT_NODE_DESCRIPTOR_SIZE:
        return []
    entries: list[int] = []
    for j in range(num_records + 1):
        value = _u16(node, array_start + 2 * j)
        if value is None:
            return []
        entries.append(value)

    starts = [entries[num_records - i] for i in range(num_records)]
    ranges: list[tuple[int, int]] = []
    for i, start in enumerate(starts):
        if i + 1 < len(starts):
            end = starts[i + 1]
        else:
            # The last record ends at the free space offset, or at the
            # beginning of the offset array when the node is completely full.
            end = entries[0] if entries[0] > start else array_start
        if start < HFSPLUS_BT_NODE_DESCRIPTOR_SIZE or end > node_size or end <= start:
            continue
        ranges.append((start, end))
    return ranges


@dataclass(frozen=True)
class _CatalogRecord:
    """A decoded catalog file or folder record."""

    record_type: int
    parent_id: int
    name: str
    cnid: int
    size: int
    modified: float | None
    is_hidden: bool


def _decode_name(raw: bytes) -> str:
    """Decode a ``HFSUniStr255`` name (UTF-16, big endian)."""
    if len(raw) < 2:
        return ""
    length = _u16(raw, 0)
    if length is None:
        return ""
    payload = raw[2 : 2 + length * 2]
    try:
        return payload.decode("utf-16-be")
    except UnicodeDecodeError:
        return payload.decode("utf-16-be", errors="replace")


def _normalise(name: str) -> str:
    """Normalise a name for comparison (HFS Plus compares case insensitively)."""
    return unicodedata.normalize("NFC", name).casefold()


def _parse_catalog_record(raw: bytes) -> _CatalogRecord | None:
    """Decode one keyed catalog record (``keyLength``, key, data)."""
    if len(raw) < 2:
        return None
    key_length = _u16(raw, 0)
    if key_length is None or key_length < 6 or 2 + key_length > len(raw):
        return None
    parent_id = _u32(raw, 2)
    if parent_id is None:
        return None
    name = _decode_name(raw[6 : 2 + key_length])

    data_offset = 2 + key_length
    if data_offset % 2:
        data_offset += 1
    data = raw[data_offset:]
    if len(data) < HFSPLUS_CATALOG_OFF_MOD_DATE + 4:
        return None

    record_type = _u16(data, HFSPLUS_CATALOG_OFF_RECORD_TYPE)
    flags = _u16(data, HFSPLUS_CATALOG_OFF_FLAGS)
    cnid = _u32(data, HFSPLUS_CATALOG_OFF_CNID)
    mod_date = _u32(data, HFSPLUS_CATALOG_OFF_MOD_DATE)
    if None in (record_type, flags, cnid, mod_date):
        return None

    size = 0
    if record_type == HFSPLUS_CATALOG_FILE_RECORD:
        expected = HFSPLUS_CATALOG_FILE_RECORD_SIZE
        logical_size = _u64(data, HFSPLUS_CATALOG_FILE_OFF_DATA_FORK)
        if logical_size is not None:
            size = logical_size
    elif record_type == HFSPLUS_CATALOG_FOLDER_RECORD:
        expected = HFSPLUS_CATALOG_FOLDER_RECORD_SIZE
    else:
        expected = 0
    if expected and len(data) < expected:
        logger.debug(
            "hfsplus: truncated catalog record (%d bytes, expected %d)", len(data), expected
        )

    modified = float(mod_date - HFSPLUS_EPOCH_OFFSET) if mod_date else None
    return _CatalogRecord(
        record_type=record_type,
        parent_id=parent_id,
        name=name,
        cnid=cnid,
        size=size,
        modified=modified,
        is_hidden=bool(flags & HFSPLUS_FLAG_INVISIBLE),
    )


def _iter_leaf_records(
    ctx: ProbeContext, fork: _ForkReader, btree: _BTreeHeader
):
    """Yield the catalog records of every leaf node, in key order.

    The leaf nodes are chained through the ``fLink`` field of the node
    descriptor; the chain is walked with a hard cap on the number of visited
    nodes so that a damaged catalog cannot loop forever.
    """
    node_number = btree.first_leaf_node
    visited = 0
    seen: set[int] = set()
    while node_number > 0 and visited < HFSPLUS_MAX_LEAF_NODES:
        if node_number in seen:
            logger.warning("hfsplus: catalog leaf chain loops at node %d", node_number)
            return
        seen.add(node_number)
        if btree.total_nodes and node_number >= btree.total_nodes:
            return
        visited += 1

        node = fork.read(ctx, node_number * btree.node_size, btree.node_size)
        if len(node) < HFSPLUS_BT_NODE_DESCRIPTOR_SIZE:
            return
        kind = struct.unpack_from(">b", node, 8)[0]
        num_records = _u16(node, 10)
        f_link = _u32(node, 0)
        if kind != HFSPLUS_BT_KIND_LEAF or num_records is None:
            return
        for start, end in _record_ranges(node, num_records):
            record = _parse_catalog_record(node[start:end])
            if record is not None:
                yield record
        if not f_link:
            return
        node_number = f_link


def read_directory(ctx: ProbeContext, path: tuple[str, ...] = ()) -> list[DirEntry]:
    """List a directory of an HFS Plus volume, read-only.

    ``path`` is a tuple of directory names relative to the volume root; the
    empty tuple lists the root folder.

    The listing is produced from the catalog B-tree: the volume header gives
    the extents of the catalog file, the catalog header node gives the node
    size and the first leaf node, and the leaf nodes are walked through their
    ``fLink`` chain.  Catalog keys are ordered by parent CNID and then by
    name, so the children of a folder are contiguous in that order.

    Names are compared case insensitively and Unicode normalised, as HFS
    Plus does.  Any inconsistency (truncated volume, damaged B-tree, short
    read) yields an empty or partial listing instead of an exception.
    """
    try:
        header = _read_volume_header(ctx)
        if header is None or not header.catalog_extents:
            return []

        fork = _ForkReader(
            header.catalog_extents, header.block_size, header.catalog_logical_size
        )
        node_zero = fork.read(ctx, 0, HFSPLUS_BT_MAX_NODE_SIZE)
        if len(node_zero) < HFSPLUS_BT_NODE_DESCRIPTOR_SIZE:
            return []
        btree = _read_btree_header(node_zero)
        if btree is None:
            return []
        if not _is_power_of_two(btree.node_size):
            return []
        if btree.node_size < HFSPLUS_BT_MIN_NODE_SIZE or (
            btree.node_size > HFSPLUS_BT_MAX_NODE_SIZE
        ):
            return []

        wanted = [_normalise(part) for part in path]
        target_cnid = HFSPLUS_ROOT_FOLDER_ID
        path_index = 0
        entries: list[DirEntry] = []

        for record in _iter_leaf_records(ctx, fork, btree):
            if record.record_type not in (
                HFSPLUS_CATALOG_FOLDER_RECORD,
                HFSPLUS_CATALOG_FILE_RECORD,
            ):
                continue
            if path_index < len(wanted):
                if record.parent_id != target_cnid:
                    continue
                if _normalise(record.name) != wanted[path_index]:
                    continue
                if record.record_type != HFSPLUS_CATALOG_FOLDER_RECORD:
                    # A file in the middle of the path: not a directory.
                    return []
                target_cnid = record.cnid
                path_index += 1
                continue
            if record.parent_id != target_cnid:
                continue
            if len(entries) >= HFSPLUS_MAX_RECORDS:
                logger.warning("hfsplus: directory listing truncated")
                break
            entries.append(
                DirEntry(
                    name=record.name,
                    is_dir=record.record_type == HFSPLUS_CATALOG_FOLDER_RECORD,
                    size=record.size,
                    modified=record.modified,
                    inode=record.cnid,
                    is_hidden=record.is_hidden,
                )
            )
        return entries
    except Exception:  # pragma: no cover - corrupt disks must not raise
        logger.debug("hfsplus: directory listing failed", exc_info=True)
        return []
