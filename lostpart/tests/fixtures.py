"""Shared test fixtures: an in-memory device and synthetic disk images."""

from __future__ import annotations

import struct

import pytest

from lostpart.device import RawDevice


class FakeDevice(RawDevice):
    """A device backed by a bytearray, recording every write."""

    def __init__(self, data: bytes = b"", sector_size: int = 512) -> None:
        self.buffer = bytearray(data)
        self.sector_size = sector_size
        self.size = len(self.buffer)
        self.writes: list[tuple[int, bytes]] = []
        self._readonly = False

    def read_at(self, offset: int, size: int) -> bytes:
        if offset < 0 or size < 0:
            raise ValueError("negative offset or size")
        if offset + size > len(self.buffer):
            raise ValueError(f"read beyond the end of the device: {offset}+{size}")
        return bytes(self.buffer[offset:offset + size])

    def write_at(self, offset: int, data: bytes) -> None:
        if self._readonly:
            raise OSError("read-only")
        if offset + len(data) > len(self.buffer):
            self.buffer.extend(b"\x00" * (offset + len(data) - len(self.buffer)))
        self.buffer[offset:offset + len(data)] = data
        self.writes.append((offset, bytes(data)))

    @property
    def is_readonly(self) -> bool:
        return self._readonly


@pytest.fixture
def fake_device() -> FakeDevice:
    return FakeDevice()


# --------------------------------------------------------------------------
# MBR
# --------------------------------------------------------------------------


def mbr_entry(
    start_lba: int,
    sector_count: int,
    type_byte: int,
    boot_indicator: int = 0x00,
) -> bytes:
    return struct.pack(
        "<BBBBBBBBII",
        boot_indicator, 0x00, 0x01, 0x00, type_byte,
        0xFE, 0xFF, 0xFF, start_lba, sector_count,
    )


def make_mbr(entries: list[bytes], bootstrap: bytes = b"") -> bytes:
    """Build a 512 byte MBR sector with the given raw entries."""
    sector = bytearray(b"\x00" * 512)
    if bootstrap:
        sector[0:len(bootstrap)] = bootstrap[:446]
    for i, entry in enumerate(entries[:4]):
        sector[0x1BE + i * 16:0x1BE + (i + 1) * 16] = entry
    sector[0x1FE] = 0x55
    sector[0x1FF] = 0xAA
    return bytes(sector)


# --------------------------------------------------------------------------
# GPT
# --------------------------------------------------------------------------


def make_gpt_disk(
    total_sectors: int = 2048,
    entries: list[tuple[str, int, int, str]] | None = None,
    entry_count: int = 128,
    entry_size: int = 128,
) -> bytes:
    """Build a disk image with a valid GPT (primary and backup).

    ``entries`` is a list of ``(type_guid, unique_guid, first_lba, name)``.
    The last usable LBA is derived from the disk size.
    """
    from lostpart.tables.gpt import (
        build_gpt_header,
        build_protective_mbr,
        crc32,
        guid_to_bytes,
    )

    sector_size = 512
    array_sectors = (entry_count * entry_size + sector_size - 1) // sector_size
    last_lba = total_sectors - 1
    first_usable = 2 + array_sectors
    last_usable = last_lba - array_sectors

    array = bytearray(entry_count * entry_size)
    for index, (type_guid, unique_guid, first_lba, name) in enumerate(entries or []):
        name_bytes = name.encode("utf-16-le")[:70].ljust(72, b"\x00")
        array[index * entry_size:(index + 1) * entry_size] = (
            guid_to_bytes(type_guid)
            + guid_to_bytes(unique_guid)
            + struct.pack("<QQQ", first_lba, first_lba + 1, 0)
            + name_bytes
        )

    array_crc = crc32(bytes(array))
    disk_guid = "11111111-2222-3333-4444-555555555555"
    primary = build_gpt_header(
        current_lba=1,
        backup_lba=last_lba,
        first_usable_lba=first_usable,
        last_usable_lba=last_usable,
        disk_guid=disk_guid,
        partition_entry_lba=2,
        partition_entry_count=entry_count,
        partition_entry_size=entry_size,
        partition_entry_array_crc32=array_crc,
    )
    backup_entry_lba = last_lba - array_sectors
    backup = build_gpt_header(
        current_lba=last_lba,
        backup_lba=1,
        first_usable_lba=first_usable,
        last_usable_lba=last_usable,
        disk_guid=disk_guid,
        partition_entry_lba=backup_entry_lba,
        partition_entry_count=entry_count,
        partition_entry_size=entry_size,
        partition_entry_array_crc32=array_crc,
    )

    disk = bytearray(total_sectors * sector_size)
    disk[0:512] = build_protective_mbr(total_sectors)
    disk[512:1024] = primary
    disk[1024:1024 + len(array)] = array
    disk[backup_entry_lba * sector_size:backup_entry_lba * sector_size + len(array)] = array
    disk[last_lba * sector_size:last_lba * sector_size + 512] = backup
    return bytes(disk)


# --------------------------------------------------------------------------
# NTFS
# --------------------------------------------------------------------------


def make_ntfs_boot_sector(
    bytes_per_sector: int = 512,
    sectors_per_cluster: int = 8,
    total_sectors: int = 4096,
    mft_lcn: int = 1,
    volume_serial: int = 0x1234ABCD,
    backup: bool = False,
) -> bytes:
    """Build a valid NTFS volume boot sector."""
    sector = bytearray(b"\x00" * 512)
    sector[0:3] = b"\xEB\x52\x90"
    sector[3:11] = b"NTFS    "
    struct.pack_into("<H", sector, 0x0B, bytes_per_sector)
    sector[0x0D] = sectors_per_cluster
    struct.pack_into("<H", sector, 0x0E, 0)
    sector[0x15] = 0xF8
    struct.pack_into("<H", sector, 0x18, 63)
    struct.pack_into("<H", sector, 0x1A, 255)
    struct.pack_into("<I", sector, 0x1C, 0)
    struct.pack_into("<Q", sector, 0x28, total_sectors)
    struct.pack_into("<Q", sector, 0x30, mft_lcn)
    struct.pack_into("<Q", sector, 0x38, 4)
    # clusters per file record: 2^(-value) bytes -> -10 means 1024 bytes
    struct.pack_into("<b", sector, 0x40, -10)
    struct.pack_into("<Q", sector, 0x48, volume_serial)
    struct.pack_into("<I", sector, 0x50, 0)
    sector[0x1FE] = 0x55
    sector[0x1FF] = 0xAA
    return bytes(sector)


def build_runlist(runs: list[tuple[int, int]]) -> bytes:
    """Encode ``(length_clusters, lcn)`` pairs as an NTFS runlist."""
    out = bytearray()
    previous = 0
    for length, lcn in runs:
        offset = lcn - previous
        length_bytes = length.to_bytes(2, "little")
        if offset < 0:
            offset_bytes = (offset & ((1 << 64) - 1)).to_bytes(4, "little")
            header = (len(offset_bytes) << 4) | len(length_bytes)
        else:
            offset_bytes = offset.to_bytes(4, "little")
            header = (len(offset_bytes) << 4) | len(length_bytes)
        out.append(header)
        out += length_bytes
        out += offset_bytes
        previous = lcn
    return bytes(out)


def build_non_resident_data_attribute(
    runs: list[tuple[int, int]],
    real_size: int,
    allocated_size: int,
    type_code: int = 0x80,
) -> bytes:
    """Build a non-resident $DATA attribute with the given runlist."""
    runlist = build_runlist(runs)
    header = bytearray(b"\x00" * 0x40)
    struct.pack_into("<I", header, 0x00, type_code)
    struct.pack_into("<I", header, 0x04, 0x40 + len(runlist))
    header[0x08] = 1  # non resident
    struct.pack_into("<H", header, 0x0A, 0)
    struct.pack_into("<H", header, 0x0C, 0)
    struct.pack_into("<H", header, 0x0E, 0)
    struct.pack_into("<Q", header, 0x10, 0)  # starting VCN
    struct.pack_into("<Q", header, 0x18, sum(length for length, _ in runs) - 1)
    struct.pack_into("<H", header, 0x20, 0x40)  # runlist offset
    struct.pack_into("<Q", header, 0x28, allocated_size)
    struct.pack_into("<Q", header, 0x30, real_size)
    struct.pack_into("<Q", header, 0x38, real_size)
    return bytes(header) + runlist


def build_mft_record(
    record_number: int,
    attributes: list[bytes],
    flags: int = 0x0001,
    sector_size: int = 512,
    record_size: int = 1024,
) -> bytes:
    """Build a complete MFT record with the update sequence array applied."""
    record = bytearray(b"\x00" * record_size)
    record[0:4] = b"FILE"
    usa_offset = 0x30
    sectors = record_size // sector_size
    usa_count = sectors + 1
    struct.pack_into("<H", record, 0x04, usa_offset)
    struct.pack_into("<H", record, 0x06, usa_count)
    struct.pack_into("<Q", record, 0x08, 1)
    struct.pack_into("<H", record, 0x10, 1)
    struct.pack_into("<H", record, 0x12, 1)
    attr_offset = usa_offset + usa_count * 2
    struct.pack_into("<H", record, 0x14, attr_offset)
    struct.pack_into("<H", record, 0x16, flags)
    struct.pack_into("<I", record, 0x2C, record_number)

    pos = attr_offset
    for attribute in attributes:
        record[pos:pos + len(attribute)] = attribute
        pos += len(attribute)
    struct.pack_into("<I", record, pos, 0xFFFFFFFF)
    used = pos + 4
    struct.pack_into("<I", record, 0x18, used)
    struct.pack_into("<I", record, 0x1C, record_size)

    # Apply the update sequence array: the last two bytes of every sector
    # carry the sequence number, the originals are kept in the array.
    usn = 0x0001
    originals = []
    for i in range(sectors):
        pos = (i + 1) * sector_size - 2
        originals.append(bytes(record[pos:pos + 2]))
    struct.pack_into("<H", record, usa_offset, usn)
    for i, original in enumerate(originals):
        struct.pack_into("<H", record, usa_offset + (i + 1) * 2,
                         struct.unpack_from("<H", original, 0)[0])
    for i in range(sectors):
        pos = (i + 1) * sector_size - 2
        struct.pack_into("<H", record, pos, usn)
    return bytes(record)


def make_ntfs_volume(
    total_clusters: int = 64,
    sectors_per_cluster: int = 8,
    allocated_clusters: int = 32,
    start_sector: int = 2048,
) -> bytes:
    """Build a synthetic NTFS volume with a real $MFT and $Bitmap.

    The volume is laid out as:

    * cluster 0: the boot sector;
    * clusters 1..2: the $MFT (records 0 and 6);
    * cluster 3: the $Bitmap;
    * clusters 4..: data clusters.  The first ``allocated_clusters`` of them
      are marked as allocated in the bitmap and filled with data, the rest
      stay zeroed and free.

    The bitmap and the data on disk agree, so the bitmap matcher must
    confirm the volume and report its extent.
    """
    bytes_per_sector = 512
    cluster_size = bytes_per_sector * sectors_per_cluster
    record_size = 1024

    total_sectors = total_clusters * sectors_per_cluster
    volume = bytearray(total_sectors * bytes_per_sector)

    mft_clusters = 2
    mft_lcn = 1
    bitmap_cluster = 3
    data_lcn = 4

    # --- the allocation bitmap -----------------------------------------
    data_clusters = max(0, min(allocated_clusters, total_clusters - data_lcn))
    bitmap = bytearray((total_clusters + 7) // 8)
    for cluster in range(data_lcn + data_clusters):
        bitmap[cluster >> 3] |= 1 << (cluster & 7)

    # --- the $MFT records ----------------------------------------------
    mft_attr = build_non_resident_data_attribute(
        [(mft_clusters, mft_lcn)],
        real_size=record_size * 16,
        allocated_size=mft_clusters * cluster_size,
    )
    record0 = build_mft_record(0, [mft_attr], record_size=record_size)

    bitmap_attr = build_non_resident_data_attribute(
        [(1, bitmap_cluster)],
        real_size=len(bitmap),
        allocated_size=cluster_size,
    )
    record6 = build_mft_record(6, [bitmap_attr], record_size=record_size)

    mft_offset = mft_lcn * cluster_size
    volume[mft_offset:mft_offset + len(record0)] = record0
    # The $Bitmap meta-file lives in MFT record 6.
    record6_offset = mft_offset + 6 * record_size
    volume[record6_offset:record6_offset + len(record6)] = record6

    bitmap_offset = bitmap_cluster * cluster_size
    volume[bitmap_offset:bitmap_offset + len(bitmap)] = bitmap

    # --- data clusters --------------------------------------------------
    for index in range(data_clusters):
        start = (data_lcn + index) * cluster_size
        pattern = bytes([(index * 7 + 13) & 0xFF]) * cluster_size
        volume[start:start + cluster_size] = pattern

    # --- the boot sector -------------------------------------------------
    boot = make_ntfs_boot_sector(
        bytes_per_sector=bytes_per_sector,
        sectors_per_cluster=sectors_per_cluster,
        total_sectors=total_sectors,
        mft_lcn=mft_lcn,
    )
    volume[0:512] = boot

    # The backup boot sector sits 16 sectors into the volume.
    volume[16 * bytes_per_sector:16 * bytes_per_sector + 512] = boot

    return bytes(volume)


def make_disk_with_ntfs(
    total_sectors: int = 8192,
    volume_start: int = 2048,
    total_clusters: int = 64,
    allocated_clusters: int = 32,
) -> bytes:
    """Build a disk image with an MBR and an NTFS volume in the free space."""
    volume = make_ntfs_volume(
        total_clusters=total_clusters,
        allocated_clusters=allocated_clusters,
    )
    disk = bytearray(total_sectors * 512)
    disk[0:512] = make_mbr([
        mbr_entry(2048, 1024, 0x07),
    ])
    offset = volume_start * 512
    disk[offset:offset + len(volume)] = volume
    return bytes(disk)
