"""ext2 / ext3 / ext4 probe and read-only directory browser.

The on-disk structures implemented here are described by the Linux
``Documentation/filesystems/ext2`` document, which documents
``struct ext2_super_block`` (the superblock that starts 1024 bytes into the
filesystem), ``struct ext2_inode`` and ``struct ext2_group_desc``.  The ext4
additions (extent trees, the 64 bit feature flag, the larger inode and group
descriptor sizes) are described by the same document.

Everything is read-only: this module never writes to the device.
"""

from __future__ import annotations

import logging
import struct
import uuid as uuid_module
from dataclasses import dataclass
from typing import Final

from ..constants import (
    EXT_FEATURE_COMPAT_HAS_JOURNAL,
    EXT_FEATURE_INCOMPAT_64BIT,
    EXT_FEATURE_INCOMPAT_EXTENTS,
    EXT_OFF_BLOCKS_COUNT,
    EXT_OFF_BLOCKS_PER_GROUP,
    EXT_OFF_FEATURE_COMPAT,
    EXT_OFF_FEATURE_INCOMPAT,
    EXT_OFF_FEATURE_RO_COMPAT,
    EXT_OFF_FEATURE_RO_COMPAT_HUGE,
    EXT_OFF_FIRST_DATA_BLOCK,
    EXT_OFF_INODES_COUNT,
    EXT_OFF_INODES_PER_GROUP,
    EXT_OFF_LAST_MOUNTED,
    EXT_OFF_LOG_BLOCK_SIZE,
    EXT_OFF_MAGIC,
    EXT_OFF_STATE,
    EXT_OFF_UUID,
    EXT_OFF_VOLUME_NAME,
    EXT_ROOT_INODE,
    EXT_S_IFDIR,
    EXT_S_IFMT,
    EXT_S_IFLNK,
    EXT_S_IFREG,
    EXT_SUPERBLOCK_MAGIC,
    EXT_SUPERBLOCK_OFFSET,
)
from .base import DirEntry, ProbeContext, ProbeResult

logger = logging.getLogger(__name__)

#: Identifier reported by the registry for this module.
FS_TYPE: Final = "ext4"

# --------------------------------------------------------------------------
# On-disk constants (see Documentation/filesystems/ext2)
# --------------------------------------------------------------------------

#: Size of the on-disk superblock in bytes.
EXT_SUPERBLOCK_SIZE: Final = 1024
#: Smallest and largest legal ext block size.
EXT_MIN_BLOCK_SIZE: Final = 1024
EXT_MAX_BLOCK_SIZE: Final = 65536
#: Block size that implies a first data block of zero.
EXT_BLOCK_SIZE_4K: Final = 4096
#: Size of one inode table entry.
EXT_INODE_SIZE: Final = 128
#: Size of one inode table entry when EXT_FEATURE_RO_COMPAT_HUGE is set.
EXT_INODE_SIZE_HUGE: Final = 256
#: Size of one group descriptor.
EXT_GROUP_DESC_SIZE: Final = 32
#: Size of one group descriptor when the 64 bit feature is set.
EXT_GROUP_DESC_SIZE_64BIT: Final = 64
#: Byte offset of ``s_desc_size`` inside the superblock.
EXT_OFF_DESC_SIZE: Final = 0xFE

#: Inode field offsets.
EXT_INODE_OFF_MODE: Final = 0x00
EXT_INODE_OFF_SIZE_LO: Final = 0x04
EXT_INODE_OFF_MTIME: Final = 0x10
EXT_INODE_OFF_LINKS_COUNT: Final = 0x1A
EXT_INODE_OFF_BLOCKS: Final = 0x1C
EXT_INODE_OFF_FLAGS: Final = 0x20
EXT_INODE_OFF_BLOCK_MAP: Final = 0x28
EXT_INODE_OFF_SIZE_HI: Final = 0x6C
#: Number of block pointers stored inside an inode.
EXT_INODE_BLOCK_MAP_COUNT: Final = 15
#: Number of direct block pointers stored inside an inode.
EXT_INODE_DIRECT_COUNT: Final = 12

#: Group descriptor field offsets.
EXT_GD_OFF_INODE_TABLE_LO: Final = 0x08
EXT_GD_OFF_INODE_TABLE_HI: Final = 0x30

#: Magic number of an ext4 extent tree header.
EXT_EXTENT_MAGIC: Final = 0xF30A
#: Size of an extent tree header / extent / extent index entry.
EXT_EXTENT_HEADER_SIZE: Final = 12
EXT_EXTENT_ENTRY_SIZE: Final = 12

#: ``file_type`` values of an ``ext4_dir_entry_2`` record.
EXT_FT_UNKNOWN: Final = 0
EXT_FT_REG: Final = 1
EXT_FT_DIR: Final = 2
EXT_FT_SYMLINK: Final = 7

#: Safety limits.  A corrupt filesystem must never turn into an endless loop.
EXT_MAX_DIR_ENTRIES: Final = 65536
EXT_MAX_FILE_BLOCKS: Final = 1 << 20
EXT_MAX_TREE_BLOCKS: Final = 1 << 16
EXT_MAX_GROUP_DESC_BYTES: Final = 1 << 20


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def _u16(buf: bytes, off: int) -> int | None:
    """Return the little endian ``u16`` at ``off`` or ``None`` if truncated."""
    if off < 0 or off + 2 > len(buf):
        return None
    return struct.unpack_from("<H", buf, off)[0]


def _u32(buf: bytes, off: int) -> int | None:
    """Return the little endian ``u32`` at ``off`` or ``None`` if truncated."""
    if off < 0 or off + 4 > len(buf):
        return None
    return struct.unpack_from("<I", buf, off)[0]


def _cstring(raw: bytes) -> str:
    """Decode a NUL terminated, possibly unprintable byte string."""
    text = raw.split(b"\x00", 1)[0]
    return text.decode("utf-8", errors="replace").strip()


def _is_power_of_two(value: int) -> bool:
    return value > 0 and (value & (value - 1)) == 0


# --------------------------------------------------------------------------
# Superblock
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Superblock:
    """The subset of ``struct ext2_super_block`` this module needs."""

    inodes_count: int
    blocks_count: int
    first_data_block: int
    block_size: int
    blocks_per_group: int
    inodes_per_group: int
    state: int
    feature_compat: int
    feature_incompat: int
    feature_ro_compat: int
    uuid: bytes
    volume_name: str
    last_mounted: str
    desc_size: int

    @property
    def inode_size(self) -> int:
        """Size of one inode table entry."""
        if self.feature_ro_compat & EXT_OFF_FEATURE_RO_COMPAT_HUGE:
            return EXT_INODE_SIZE_HUGE
        return EXT_INODE_SIZE

    @property
    def has_extents(self) -> bool:
        """True when the inode block map is an extent tree."""
        return bool(self.feature_incompat & EXT_FEATURE_INCOMPAT_EXTENTS)

    @property
    def is_64bit(self) -> bool:
        """True when the filesystem uses 64 bit block and inode numbers."""
        return bool(self.feature_incompat & EXT_FEATURE_INCOMPAT_64BIT)


def _read_superblock(ctx: ProbeContext) -> _Superblock | None:
    """Parse and validate the ext superblock of the candidate volume.

    The superblock starts 1024 bytes into the filesystem, so it is read at
    ``EXT_SUPERBLOCK_OFFSET``.  ``None`` is returned when the structure does
    not describe a usable ext filesystem (bad magic, impossible geometry, or
    a block count that does not fit inside the candidate volume).
    """
    try:
        raw = ctx.read(EXT_SUPERBLOCK_OFFSET, EXT_SUPERBLOCK_SIZE)
    except Exception:  # pragma: no cover - device error
        logger.debug("ext: cannot read superblock", exc_info=True)
        return None
    if len(raw) < EXT_SUPERBLOCK_SIZE:
        return None

    magic = _u16(raw, EXT_OFF_MAGIC)
    if magic != EXT_SUPERBLOCK_MAGIC:
        return None

    log_block_size = _u32(raw, EXT_OFF_LOG_BLOCK_SIZE)
    inodes_count = _u32(raw, EXT_OFF_INODES_COUNT)
    blocks_count = _u32(raw, EXT_OFF_BLOCKS_COUNT)
    first_data_block = _u32(raw, EXT_OFF_FIRST_DATA_BLOCK)
    blocks_per_group = _u32(raw, EXT_OFF_BLOCKS_PER_GROUP)
    inodes_per_group = _u32(raw, EXT_OFF_INODES_PER_GROUP)
    state = _u16(raw, EXT_OFF_STATE)
    feature_compat = _u32(raw, EXT_OFF_FEATURE_COMPAT)
    feature_incompat = _u32(raw, EXT_OFF_FEATURE_INCOMPAT)
    feature_ro_compat = _u32(raw, EXT_OFF_FEATURE_RO_COMPAT)

    if (
        log_block_size is None
        or inodes_count is None
        or blocks_count is None
        or first_data_block is None
        or blocks_per_group is None
        or inodes_per_group is None
        or state is None
        or feature_compat is None
        or feature_incompat is None
        or feature_ro_compat is None
    ):
        return None

    block_size = EXT_MIN_BLOCK_SIZE << log_block_size
    if (
        not _is_power_of_two(block_size)
        or block_size < EXT_MIN_BLOCK_SIZE
        or block_size > EXT_MAX_BLOCK_SIZE
    ):
        return None
    if inodes_count <= 0 or blocks_count <= 0:
        return None
    if blocks_per_group <= 0 or inodes_per_group <= 0:
        return None
    expected_first = 0 if block_size == EXT_BLOCK_SIZE_4K else 1
    if first_data_block != expected_first:
        return None
    if blocks_count * block_size > ctx.volume_bytes():
        return None

    desc_size = EXT_GROUP_DESC_SIZE
    if feature_incompat & EXT_FEATURE_INCOMPAT_64BIT:
        stored = _u16(raw, EXT_OFF_DESC_SIZE)
        if stored is not None and stored >= EXT_GROUP_DESC_SIZE:
            desc_size = stored

    return _Superblock(
        inodes_count=inodes_count,
        blocks_count=blocks_count,
        first_data_block=first_data_block,
        block_size=block_size,
        blocks_per_group=blocks_per_group,
        inodes_per_group=inodes_per_group,
        state=state,
        feature_compat=feature_compat,
        feature_incompat=feature_incompat,
        feature_ro_compat=feature_ro_compat,
        uuid=raw[EXT_OFF_UUID : EXT_OFF_UUID + 16],
        volume_name=_cstring(raw[EXT_OFF_VOLUME_NAME : EXT_OFF_VOLUME_NAME + 16]),
        last_mounted=_cstring(
            raw[EXT_OFF_LAST_MOUNTED : EXT_OFF_LAST_MOUNTED + 64]
        ),
        desc_size=desc_size,
    )


def _revision(sb: _Superblock) -> str:
    """Return the filesystem revision implied by the feature flags.

    ext4 is recognised by ``EXT_FEATURE_INCOMPAT_EXTENTS``, ext3 by
    ``EXT_FEATURE_COMPAT_HAS_JOURNAL``; everything else is ext2.
    """
    if sb.feature_incompat & EXT_FEATURE_INCOMPAT_EXTENTS:
        return "ext4"
    if sb.feature_compat & EXT_FEATURE_COMPAT_HAS_JOURNAL:
        return "ext3"
    return "ext2"


def detect(ctx: ProbeContext) -> ProbeResult | None:
    """Detect an ext2/ext3/ext4 filesystem at the start of a volume.

    The superblock is expected 1024 bytes into the candidate volume.  The
    confidence ladder is:

    ============================================  =======
    Evidence                                      Weight
    ============================================  =======
    magic ``0xEF53`` at offset 1024               +0.55
    plausible block size (1024..65536, pow2)       +0.15
    block count fits inside the candidate volume  +0.10
    sane group / inode geometry                    +0.10
    clean filesystem (``s_state == 1``)            +0.05
    ext3/ext4 feature bit present                  +0.05
    ============================================  =======

    Anything that contradicts the on-disk layout (wrong magic, impossible
    block size, a block count larger than the volume, ...) makes the probe
    return ``None``.
    """
    sb = _read_superblock(ctx)
    if sb is None:
        return None

    evidence: list[str] = [
        f"ext superblock magic 0x{EXT_SUPERBLOCK_MAGIC:04X} at offset "
        f"{EXT_SUPERBLOCK_OFFSET}"
    ]
    confidence = 0.55

    evidence.append(f"block size {sb.block_size} bytes")
    confidence += 0.15

    volume_bytes = sb.blocks_count * sb.block_size
    evidence.append(
        f"{sb.blocks_count} blocks ({volume_bytes} bytes) fit in the candidate volume"
    )
    confidence += 0.10

    evidence.append(
        f"geometry sane: {sb.blocks_per_group} blocks/group, "
        f"{sb.inodes_per_group} inodes/group, {sb.inodes_count} inodes"
    )
    confidence += 0.10

    if sb.state == 1:
        evidence.append("filesystem is clean (state=1)")
        confidence += 0.05
    else:
        evidence.append(f"filesystem is not clean (state={sb.state})")

    revision = _revision(sb)
    if revision != "ext2":
        evidence.append(f"{revision} feature bits present")
        confidence += 0.05
    else:
        evidence.append("no journal and no extent feature bits (ext2 layout)")

    confidence = min(confidence, 1.0)

    label = sb.volume_name or f"{revision} filesystem"
    details: dict[str, object] = {
        "block_size": sb.block_size,
        "blocks_count": sb.blocks_count,
        "inodes_count": sb.inodes_count,
        "blocks_per_group": sb.blocks_per_group,
        "inodes_per_group": sb.inodes_per_group,
        "first_data_block": sb.first_data_block,
        "state": sb.state,
        "volume_name": sb.volume_name,
        "last_mounted": sb.last_mounted,
        "uuid": _format_uuid(sb.uuid),
        "revision": revision,
        "inode_size": sb.inode_size,
        "desc_size": sb.desc_size,
        "bytes_per_sector": ctx.sector_size,
    }
    total_bytes = sb.blocks_count * sb.block_size
    details["total_sectors"] = total_bytes // ctx.sector_size
    if sb.block_size >= ctx.sector_size:
        details["sectors_per_cluster"] = sb.block_size // ctx.sector_size

    return ProbeResult(
        fs_type=revision,
        label=label,
        confidence=confidence,
        details=details,
        evidence=tuple(evidence),
    )


def _format_uuid(raw: bytes) -> str:
    """Format the 16 raw uuid bytes as a canonical UUID string."""
    if len(raw) != 16:
        return ""
    return str(uuid_module.UUID(bytes=bytes(raw)))


# --------------------------------------------------------------------------
# Inode handling
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Inode:
    """The subset of ``struct ext2_inode`` this module needs."""

    number: int
    mode: int
    size: int
    mtime: int
    links_count: int
    blocks: int
    flags: int
    block_map: bytes

    @property
    def is_dir(self) -> bool:
        return (self.mode & EXT_S_IFMT) == EXT_S_IFDIR

    @property
    def is_reg(self) -> bool:
        return (self.mode & EXT_S_IFMT) == EXT_S_IFREG

    @property
    def is_symlink(self) -> bool:
        return (self.mode & EXT_S_IFMT) == EXT_S_IFLNK


def _read_block(ctx: ProbeContext, sb: _Superblock, block: int) -> bytes | None:
    """Read one filesystem block; ``None`` when it cannot be read."""
    if block <= 0 or block >= sb.blocks_count:
        return None
    offset = block * sb.block_size
    if offset + sb.block_size > ctx.volume_bytes():
        return None
    try:
        data = ctx.read(offset, sb.block_size)
    except Exception:  # pragma: no cover - device error
        logger.debug("ext: cannot read block %d", block, exc_info=True)
        return None
    if len(data) < sb.block_size:
        return None
    return data


def _read_group_descriptor(
    ctx: ProbeContext, sb: _Superblock, group: int
) -> int | None:
    """Return the inode table block number of ``group``.

    The group descriptor table lives in block ``first_data_block + 1``; the
    descriptor of a group starts at ``group * s_desc_size`` inside it.  The
    inode table pointer is ``bg_inode_table_lo`` (plus ``bg_inode_table_hi``
    when the 64 bit feature is enabled).
    """
    if group < 0:
        return None
    desc_table_block = sb.first_data_block + 1
    offset = desc_table_block * sb.block_size + group * sb.desc_size
    if offset < 0 or offset + sb.desc_size > ctx.volume_bytes():
        return None
    try:
        raw = ctx.read(offset, sb.desc_size)
    except Exception:  # pragma: no cover - device error
        logger.debug("ext: cannot read group descriptor %d", group, exc_info=True)
        return None
    if len(raw) < sb.desc_size:
        return None

    low = _u32(raw, EXT_GD_OFF_INODE_TABLE_LO)
    if low is None:
        return None
    table = low
    if sb.is_64bit and sb.desc_size >= EXT_GROUP_DESC_SIZE_64BIT:
        high = _u32(raw, EXT_GD_OFF_INODE_TABLE_HI)
        if high is None:
            return None
        table |= high << 32
    if table <= 0 or table >= sb.blocks_count:
        return None
    return table


def _read_inode(ctx: ProbeContext, sb: _Superblock, number: int) -> _Inode | None:
    """Read inode ``number`` from the inode table of its block group."""
    if number <= 0 or number > sb.inodes_count:
        return None
    group = (number - 1) // sb.inodes_per_group
    index = (number - 1) % sb.inodes_per_group
    table = _read_group_descriptor(ctx, sb, group)
    if table is None:
        return None

    offset = table * sb.block_size + index * sb.inode_size
    if offset < 0 or offset + sb.inode_size > ctx.volume_bytes():
        return None
    try:
        raw = ctx.read(offset, sb.inode_size)
    except Exception:  # pragma: no cover - device error
        logger.debug("ext: cannot read inode %d", number, exc_info=True)
        return None
    if len(raw) < EXT_INODE_SIZE:
        return None

    mode = _u16(raw, EXT_INODE_OFF_MODE)
    size_lo = _u32(raw, EXT_INODE_OFF_SIZE_LO)
    size_hi = _u32(raw, EXT_INODE_OFF_SIZE_HI)
    mtime = _u32(raw, EXT_INODE_OFF_MTIME)
    links_count = _u16(raw, EXT_INODE_OFF_LINKS_COUNT)
    blocks = _u32(raw, EXT_INODE_OFF_BLOCKS)
    flags = _u32(raw, EXT_INODE_OFF_FLAGS)
    if None in (mode, size_lo, mtime, links_count, blocks, flags):
        return None

    size = size_lo
    if size_hi:
        size |= size_hi << 32

    block_map = raw[EXT_INODE_OFF_BLOCK_MAP : EXT_INODE_OFF_BLOCK_MAP + 60]
    if len(block_map) < 60:
        block_map = block_map.ljust(60, b"\x00")

    return _Inode(
        number=number,
        mode=mode,
        size=size,
        mtime=mtime,
        links_count=links_count,
        blocks=blocks,
        flags=flags,
        block_map=block_map,
    )


def _inode_pointers(inode: _Inode) -> list[int]:
    """Return the 15 block pointers stored in the inode."""
    pointers: list[int] = []
    for i in range(EXT_INODE_BLOCK_MAP_COUNT):
        value = _u32(inode.block_map, i * 4)
        if value is not None:
            pointers.append(value)
    return pointers


def _indirect_blocks(
    ctx: ProbeContext,
    sb: _Superblock,
    block: int,
    level: int,
    out: list[int],
    visited: set[int],
) -> None:
    """Resolve an indirect block chain into physical block numbers.

    ``level`` is the number of indirections still to follow (0 means the
    block holds the final block numbers).  Already visited blocks are skipped
    so that a corrupt filesystem cannot produce an endless loop.
    """
    if block <= 0 or level < 0 or block in visited:
        return
    if len(visited) >= EXT_MAX_TREE_BLOCKS or len(out) >= EXT_MAX_FILE_BLOCKS:
        return
    visited.add(block)

    data = _read_block(ctx, sb, block)
    if data is None:
        return
    count = len(data) // 4
    for i in range(count):
        pointer = _u32(data, i * 4)
        if not pointer:
            continue
        if level == 0:
            if len(out) >= EXT_MAX_FILE_BLOCKS:
                return
            out.append(pointer)
        else:
            _indirect_blocks(ctx, sb, pointer, level - 1, out, visited)


def _extent_blocks(
    ctx: ProbeContext,
    sb: _Superblock,
    data: bytes,
    depth: int,
    out: list[int],
    visited: set[int],
) -> None:
    """Resolve an ext4 extent tree into physical block numbers.

    ``data`` holds an extent tree node: a 12 byte header followed by the
    entries.  At depth zero the entries are extents, otherwise they are
    indexes pointing at the next level.
    """
    if depth < 0 or len(visited) >= EXT_MAX_TREE_BLOCKS:
        return
    if len(out) >= EXT_MAX_FILE_BLOCKS:
        return

    magic = _u16(data, 0)
    if magic != EXT_EXTENT_MAGIC:
        return
    entries = _u16(data, 2)
    if entries is None:
        return

    for i in range(entries):
        offset = EXT_EXTENT_HEADER_SIZE + i * EXT_EXTENT_ENTRY_SIZE
        if offset + EXT_EXTENT_ENTRY_SIZE > len(data):
            break
        if depth == 0:
            length = _u16(data, offset + 4)
            start_hi = _u16(data, offset + 6)
            start_lo = _u32(data, offset + 8)
            if length is None or start_hi is None or start_lo is None:
                continue
            # Lengths above 32768 are stored as (length - 32768).
            if length > 0x8000:
                length -= 0x8000
            physical = (start_hi << 32) | start_lo
            for k in range(length):
                if len(out) >= EXT_MAX_FILE_BLOCKS:
                    return
                out.append(physical + k)
        else:
            leaf_lo = _u32(data, offset + 4)
            leaf_hi = _u16(data, offset + 8)
            if leaf_lo is None or leaf_hi is None:
                continue
            leaf = (leaf_hi << 32) | leaf_lo
            if leaf <= 0 or leaf in visited:
                continue
            visited.add(leaf)
            leaf_data = _read_block(ctx, sb, leaf)
            if leaf_data is None:
                continue
            _extent_blocks(ctx, sb, leaf_data, depth - 1, out, visited)


def _inode_blocks(ctx: ProbeContext, sb: _Superblock, inode: _Inode) -> list[int]:
    """Return the physical block numbers of an inode, in logical order."""
    pointers = _inode_pointers(inode)
    if not pointers:
        return []

    if sb.has_extents:
        blocks: list[int] = []
        header = inode.block_map
        depth = _u16(header, 6) or 0
        _extent_blocks(ctx, sb, header, depth, blocks, set())
        return blocks

    blocks = []
    visited: set[int] = set()
    for pointer in pointers[:EXT_INODE_DIRECT_COUNT]:
        if pointer and pointer < sb.blocks_count:
            blocks.append(pointer)
    # Single, double and triple indirect blocks.
    for level, pointer in zip((1, 2, 3), pointers[EXT_INODE_DIRECT_COUNT:]):
        _indirect_blocks(ctx, sb, pointer, level, blocks, visited)
    return blocks


# --------------------------------------------------------------------------
# Directory entries
# --------------------------------------------------------------------------


def _parse_dir_block(data: bytes, out: list[DirEntry]) -> bool:
    """Parse the ``ext4_dir_entry_2`` records of one directory block.

    Returns ``False`` when the block does not contain a valid record list
    (the caller stops parsing at that point).
    """
    pos = 0
    size = len(data)
    while pos + 8 <= size:
        inode = _u32(data, pos)
        rec_len = _u16(data, pos + 4)
        if rec_len is None or inode is None:
            return False
        if rec_len < 8 or pos + rec_len > size:
            return False
        if inode == 0:
            return True

        name_len = data[pos + 6]
        file_type = data[pos + 7]
        if name_len == 0:
            # Classic ext2 directory entry: name_len is a u16 at +6.
            classic = _u16(data, pos + 6)
            if classic and classic + 8 <= rec_len:
                name_len = classic
                file_type = EXT_FT_UNKNOWN

        if name_len and 8 + name_len <= rec_len:
            raw_name = data[pos + 8 : pos + 8 + name_len]
            name = raw_name.decode("utf-8", errors="replace")
            if name not in (".", ".."):
                is_dir = file_type == EXT_FT_DIR
                out.append(
                    DirEntry(
                        name=name,
                        is_dir=is_dir,
                        size=0,
                        modified=None,
                        inode=inode,
                        is_hidden=name.startswith("."),
                    )
                )
        pos += rec_len
    return True


def _list_directory(ctx: ProbeContext, sb: _Superblock, inode: _Inode) -> list[DirEntry]:
    """List the entries of the directory described by ``inode``."""
    entries: list[DirEntry] = []
    for block in _inode_blocks(ctx, sb, inode):
        if len(entries) >= EXT_MAX_DIR_ENTRIES:
            logger.warning("ext: directory listing truncated at %d entries", len(entries))
            break
        data = _read_block(ctx, sb, block)
        if data is None:
            continue
        if not _parse_dir_block(data, entries):
            break
    return entries


def read_directory(ctx: ProbeContext, path: tuple[str, ...] = ()) -> list[DirEntry]:
    """List a directory of an ext2/ext3/ext4 volume, read-only.

    ``path`` is a tuple of directory names relative to the filesystem root.
    The empty tuple lists the root directory.

    The directory content is read through the inode block map: the twelve
    direct blocks, the single, double and triple indirect blocks and -- on
    ext4 -- the extent tree stored in ``i_block``.  Only the *names*, the
    entry type and the inode number of each child are reported; the size and
    modification time of the children are not resolved (that would require
    one extra inode read per entry).

    Any inconsistency (truncated volume, broken group descriptor, damaged
    extent tree) results in an empty or partial listing instead of an
    exception.
    """
    try:
        sb = _read_superblock(ctx)
        if sb is None:
            return []
        inode = _read_inode(ctx, sb, EXT_ROOT_INODE)
        if inode is None or not inode.is_dir:
            return []
        for name in path:
            entries = _list_directory(ctx, sb, inode)
            match = next((e for e in entries if e.name == name), None)
            if match is None or not match.is_dir or match.inode is None:
                return []
            child = _read_inode(ctx, sb, match.inode)
            if child is None or not child.is_dir:
                return []
            inode = child
        return _list_directory(ctx, sb, inode)
    except Exception:  # pragma: no cover - corrupt disks must not raise
        logger.debug("ext: directory listing failed", exc_info=True)
        return []
