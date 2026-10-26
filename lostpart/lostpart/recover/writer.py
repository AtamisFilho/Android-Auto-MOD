"""Write a recovered partition entry back to the disk.

This is the only module that modifies a disk, so it is deliberately
conservative:

* every write is preceded by a backup of the structures that are touched;
* the candidate is validated first -- the entry must not overlap an existing
  partition and must fit inside the disk;
* an MBR disk is only modified when a primary slot is free or an extended
  boot record chain can be extended;
* a GPT disk is updated in a consistent way: the entry, both entry array
  CRCs, the primary header and the backup header at the end of the disk.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from ..constants import (
    GPT_ENTRY_SIZE,
    GPT_TYPE_LINUX_BY_FS,
    MBR_TYPE_EMPTY,
    MBR_TYPE_EXTENDED_WIN,
    MBR_TYPE_LABELS,
)
from ..device import RawDevice
from ..errors import RecoveryError, ValidationError
from ..i18n import t
from ..scan.model import LostPartitionCandidate, RecoveryOutcome
from ..tables.gpt import (
    MAX_PARTITION_ENTRIES,
    MAX_PARTITION_ENTRY_SIZE,
    GptEntry,
    build_gpt_header,
    build_protective_mbr,
    crc32,
    guid_to_bytes,
    parse_gpt_entries,
    parse_gpt_header,
)
from ..tables.mbr import (
    MbrPartitionEntry,
    build_mbr_sector,
    lba_to_chs,
    parse_mbr,
)
from ..tables.table import TABLE_TYPE_GPT, PartitionTable, load_partition_table

logger = logging.getLogger(__name__)

__all__ = [
    "recover_partition",
    "validate_candidate",
    "mbr_type_for_fs",
    "gpt_type_for_fs",
    "DEFAULT_ALIGNMENT_SECTORS",
]

#: New partitions are aligned to 1 MiB by default.
DEFAULT_ALIGNMENT_SECTORS = 2048

#: MBR type byte for each filesystem we can detect.
_MBR_TYPES: dict[str, int] = {
    "ntfs": 0x07,
    "exfat": 0x07,
    "fat32": 0x0C,
    "fat16": 0x06,
    "fat12": 0x01,
    "ext2": 0x83,
    "ext3": 0x83,
    "ext4": 0x83,
    "swap": 0x82,
    "hfsplus": 0x0A,
}


def mbr_type_for_fs(fs_type: str) -> int:
    """The MBR type byte to use for a filesystem.

    An unknown filesystem is refused instead of being written as NTFS: a
    partition that claims the wrong type is mounted wrongly, or not at all,
    and the user has no way to tell that from a failed recovery.
    """
    try:
        return _MBR_TYPES[fs_type.lower()]
    except KeyError:
        raise ValueError(
            f"no MBR type byte is known for the filesystem {fs_type!r}"
        ) from None


def gpt_type_for_fs(fs_type: str) -> str:
    """The GPT partition type GUID to use for a filesystem."""
    try:
        return GPT_TYPE_LINUX_BY_FS[fs_type.lower()]
    except KeyError:
        raise ValueError(
            f"no GPT type GUID is known for the filesystem {fs_type!r}"
        ) from None


def _align_up(value: int, alignment: int) -> int:
    if alignment <= 1:
        return value
    remainder = value % alignment
    return value if remainder == 0 else value + (alignment - remainder)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def validate_candidate(
    device: RawDevice,
    table: PartitionTable,
    candidate: LostPartitionCandidate,
) -> None:
    """Check that a candidate can be written back safely.

    Raises :class:`ValidationError` when the candidate must not be written.
    """
    if candidate.sector_count <= 0:
        raise ValidationError(t("error.no_size"))
    if candidate.start_sector <= 0:
        raise ValidationError(t("error.start_zero"))
    try:
        mbr_type_for_fs(candidate.fs_type)
        gpt_type_for_fs(candidate.fs_type)
    except ValueError:
        raise ValidationError(
            t("error.unknown_fs", fs=candidate.fs_type)
        ) from None
    if candidate.end_sector > device.total_sectors:
        raise ValidationError(
            t("error.out_of_range", end=candidate.end_sector,
              total=device.total_sectors)
        )
    for entry in table.occupied:
        if candidate.start_sector < entry.end_lba and entry.start_lba < candidate.end_sector:
            raise ValidationError(
                t("error.overlap", index=entry.index, start=entry.start_lba,
                  end=entry.end_lba)
            )


# --------------------------------------------------------------------------
# MBR
# --------------------------------------------------------------------------


def _write_mbr_entry(
    device: RawDevice,
    table: PartitionTable,
    candidate: LostPartitionCandidate,
    bootable: bool,
    alignment: int,
) -> tuple[int, int]:
    """Write an MBR entry.  Returns ``(partition_index, bytes_written)``."""
    sector_size = device.sector_size or 512
    mbr = table.mbr or parse_mbr(device.read_at(0, sector_size))
    entries = list(mbr.entries)
    type_byte = mbr_type_for_fs(candidate.fs_type)
    free_slot = next((e.index for e in entries[:4] if e.is_empty), None)
    if free_slot is not None:
        head, sector, cylinder = lba_to_chs(candidate.start_sector)
        end_head, end_sector, end_cylinder = lba_to_chs(candidate.end_sector - 1)
        entries[free_slot] = MbrPartitionEntry(
            index=free_slot,
            boot_indicator=0x80 if bootable else 0x00,
            start_lba=candidate.start_sector,
            sector_count=candidate.sector_count,
            type_byte=type_byte,
            start_head=head,
            start_sector=sector,
            start_cylinder=cylinder,
            end_head=end_head,
            end_sector=end_sector,
            end_cylinder=end_cylinder,
        )
        device.write_at(0, build_mbr_sector(entries, mbr.bootstrap))
        return free_slot, 512

    # No primary slot left: extend the extended boot record chain.
    extended = mbr.extended_entry()
    if extended is None:
        raise ValidationError(t("error.mbr_full"))

    container_end = extended.end_lba
    chain: list[tuple[int, bytes]] = []
    next_ebr = extended.start_lba
    seen: set[int] = set()
    while next_ebr and next_ebr not in seen:
        seen.add(next_ebr)
        raw = device.read_at(next_ebr * sector_size, sector_size)
        if len(raw) < 512:
            break
        chain.append((next_ebr, raw))
        following = parse_mbr(raw).entries[1]
        if following.is_empty:
            break
        next_ebr = following.start_lba

    if not chain:
        raise RecoveryError(t("error.ebr_chain"))

    last_ebr_lba, last_ebr_raw = chain[-1]
    last_ebr = parse_mbr(last_ebr_raw)
    last_logical = last_ebr.entries[0]

    free_start = max(last_logical.end_lba, last_ebr_lba + 1)
    logical_start = _align_up(free_start, alignment)
    new_ebr_lba = logical_start - 1
    if new_ebr_lba < free_start:
        raise ValidationError(t("error.ebr_room"))
    if logical_start + candidate.sector_count > container_end:
        raise ValidationError(t("error.ebr_fit"))

    # The new EBR describes the recovered partition; its second entry is the
    # terminator of the chain.
    new_entries = list(new_ebr.entries)
    head, sector, cylinder = lba_to_chs(logical_start)
    end_head, end_sector, end_cylinder = lba_to_chs(logical_start + candidate.sector_count - 1)
    new_entries[0] = MbrPartitionEntry(
        index=0,
        boot_indicator=0x00,
        start_lba=logical_start,
        sector_count=candidate.sector_count,
        type_byte=type_byte,
        start_head=head,
        start_sector=sector,
        start_cylinder=cylinder,
        end_head=end_head,
        end_sector=end_sector,
        end_cylinder=end_cylinder,
    )
    new_entries[1] = MbrPartitionEntry(index=1, boot_indicator=0, start_lba=0,
                                       sector_count=0, type_byte=MBR_TYPE_EMPTY)
    new_ebr_bytes = build_mbr_sector(new_entries)

    # Link the previous EBR to the new one.
    previous_entries = list(last_ebr.entries)
    previous_entries[1] = MbrPartitionEntry(
        index=1,
        boot_indicator=0x00,
        start_lba=new_ebr_lba,
        sector_count=container_end - new_ebr_lba,
        type_byte=MBR_TYPE_EXTENDED_WIN,
    )
    previous_bytes = build_mbr_sector(previous_entries, last_ebr.bootstrap)

    device.write_at(new_ebr_lba * sector_size, new_ebr_bytes)
    device.write_at(last_ebr_lba * sector_size, previous_bytes)
    return 4, 512 * 2


# --------------------------------------------------------------------------
# GPT
# --------------------------------------------------------------------------


def _write_gpt_entry(
    device: RawDevice,
    table: PartitionTable,
    candidate: LostPartitionCandidate,
    bootable: bool,
) -> tuple[int, int]:
    """Write a GPT entry and keep both copies of the table consistent."""
    sector_size = device.sector_size or 512
    header = table.gpt_header
    if header is None:
        raise RecoveryError(t("error.gpt_header"))
    if not (0 < header.partition_entry_count <= MAX_PARTITION_ENTRIES):
        raise ValidationError(t("error.gpt_entry_count",
                                 count=header.partition_entry_count))
    if not (GPT_ENTRY_SIZE <= header.partition_entry_size <= MAX_PARTITION_ENTRY_SIZE):
        raise ValidationError(t("error.gpt_entry_size",
                                 size=header.partition_entry_size))

    array_bytes = device.read_at(
        header.partition_entry_lba * sector_size,
        header.partition_entry_count * header.partition_entry_size,
    )
    entries = parse_gpt_entries(array_bytes, header.partition_entry_count, header.partition_entry_size)

    free_index = next((e.index for e in entries if e.is_empty), None)
    if free_index is None:
        raise ValidationError(t("error.gpt_full"))

    attributes = 0
    if bootable:
        attributes |= 1 << 2
    entry = GptEntry(
        index=free_index,
        type_guid=gpt_type_for_fs(candidate.fs_type),
        unique_guid=str(uuid.uuid4()),
        first_lba=candidate.start_sector,
        last_lba=candidate.end_sector - 1,
        attributes=attributes,
        name=candidate.volume_name or candidate.label,
    )

    # The entry is 128 bytes, but the slot in the array can be wider.  It has
    # to be padded, otherwise the array would shrink by the difference and
    # every entry after it would move, taking the CRC with it.
    entry_bytes = entry.to_bytes().ljust(header.partition_entry_size, b"\x00")

    # Write the single entry into the primary array.
    entry_offset = free_index * header.partition_entry_size
    device.write_at(
        header.partition_entry_lba * sector_size + entry_offset,
        entry_bytes,
    )

    # Recompute the entry array CRC and rewrite the primary header.
    new_array = bytearray(array_bytes)
    new_array[entry_offset:entry_offset + header.partition_entry_size] = entry_bytes
    array_crc = crc32(bytes(new_array))
    primary_header = build_gpt_header(
        current_lba=header.current_lba,
        backup_lba=header.backup_lba,
        first_usable_lba=header.first_usable_lba,
        last_usable_lba=header.last_usable_lba,
        disk_guid=header.disk_guid,
        partition_entry_lba=header.partition_entry_lba,
        partition_entry_count=header.partition_entry_count,
        partition_entry_size=header.partition_entry_size,
        partition_entry_array_crc32=array_crc,
    )
    device.write_at(header.current_lba * sector_size, primary_header)

    # Mirror everything into the backup at the end of the disk.
    array_sectors = (
        header.partition_entry_count * header.partition_entry_size + sector_size - 1
    ) // sector_size
    # The backup array occupies the sectors right before the backup header.
    # One sector later and its last sector would land on the header.
    backup_entry_lba = header.backup_lba - array_sectors
    device.write_at(backup_entry_lba * sector_size, bytes(new_array))
    backup_header = build_gpt_header(
        current_lba=header.backup_lba,
        backup_lba=header.current_lba,
        first_usable_lba=header.first_usable_lba,
        last_usable_lba=header.last_usable_lba,
        disk_guid=header.disk_guid,
        partition_entry_lba=backup_entry_lba,
        partition_entry_count=header.partition_entry_count,
        partition_entry_size=header.partition_entry_size,
        partition_entry_array_crc32=array_crc,
    )
    device.write_at(header.backup_lba * sector_size, backup_header)

    # The protective MBR must stay in place on a GPT disk.
    protective = build_protective_mbr(device.total_sectors)
    current_mbr = device.read_at(0, sector_size)
    if current_mbr[0x1BE:0x1BE + 4] != b"\x00\x00\x02\x00":
        device.write_at(0, protective)

    return free_index, sector_size * (2 + array_sectors * 2)


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def recover_partition(
    device: RawDevice,
    candidate: LostPartitionCandidate,
    table: PartitionTable | None = None,
    bootable: bool = False,
    dry_run: bool = True,
    alignment: int = DEFAULT_ALIGNMENT_SECTORS,
) -> RecoveryOutcome:
    """Write a partition entry for a recovered candidate.

    With ``dry_run`` set (the default) nothing is written; the function only
    reports what would happen.
    """
    if table is None:
        table = load_partition_table(device)
    if table is None:
        raise RecoveryError(t("error.no_table"))

    validate_candidate(device, table, candidate)

    if dry_run:
        action = t(
            "recover.would_write",
            table=table.kind.upper(),
            fs=candidate.fs_type,
            start=candidate.start_sector,
            sectors=candidate.sector_count,
            size=f"{candidate.size_bytes / (1024 * 1024):.1f} MiB",
        )
        return RecoveryOutcome(
            candidate=candidate,
            success=True,
            message=action,
            table_type=table.kind,
        )

    if device.is_readonly:
        raise RecoveryError(t("error.readonly"))

    if table.kind == TABLE_TYPE_GPT:
        index, written = _write_gpt_entry(device, table, candidate, bootable)
    else:
        index, written = _write_mbr_entry(device, table, candidate, bootable, alignment)

    label = MBR_TYPE_LABELS.get(mbr_type_for_fs(candidate.fs_type), candidate.label)
    return RecoveryOutcome(
        candidate=candidate,
        success=True,
        message=t(
            "recover.wrote",
            table=table.kind.upper(),
            index=index,
            fs=candidate.fs_type,
            label=label,
            start=candidate.start_sector,
        ),
        table_type=table.kind,
        partition_index=index,
        written_bytes=written,
    )
