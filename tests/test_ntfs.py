"""Tests for the NTFS probe and the allocation bitmap matcher."""

from __future__ import annotations

from lostpart.fs.base import ProbeContext
from lostpart.fs.ntfs import (
    apply_fixups,
    decode_runlist,
    parse_boot_sector,
    parse_mft_record,
)
from lostpart.scan.bitmap_match import analyse_bitmap, find_max_used_cluster

from .fixtures import FakeDevice, make_ntfs_boot_sector, make_ntfs_volume


def _context(device: FakeDevice, start_sector: int) -> ProbeContext:
    return ProbeContext(
        device=device,
        start_sector=start_sector,
        sector_size=device.sector_size,
        total_sectors=device.total_sectors,
    )


def test_parse_boot_sector_accepts_a_valid_dbr():
    boot = parse_boot_sector(make_ntfs_boot_sector())
    assert boot is not None
    assert boot.bytes_per_sector == 512
    assert boot.sectors_per_cluster == 8
    assert boot.cluster_size == 4096
    assert boot.total_clusters == 512
    assert boot.file_record_size == 1024


def test_parse_boot_sector_rejects_random_data():
    assert parse_boot_sector(b"\x00" * 512) is None
    assert parse_boot_sector(b"") is None
    assert parse_boot_sector(make_ntfs_boot_sector()[:100]) is None


def test_parse_boot_sector_rejects_an_impossible_cluster_size():
    data = bytearray(make_ntfs_boot_sector())
    data[0x0D] = 7  # not a power of two
    assert parse_boot_sector(bytes(data)) is None


def test_decode_runlist_reads_length_and_delta():
    # length = 0x20 clusters, delta = 0x10 clusters
    runlist = bytes([0x11, 0x20, 0x10])
    assert decode_runlist(runlist) == ((0x20, 0x10),)


def test_decode_runlist_handles_sparse_runs():
    runlist = bytes([0x01, 0x08, 0x00])
    assert decode_runlist(runlist) == ((8, -1),)


def test_apply_fixups_restores_the_original_bytes():
    sector_size = 512
    record = bytearray(b"\xAA" * 1024)
    usa_offset = 0x30
    struct_pack = __import__("struct").pack_into
    struct_pack("<H", record, 0x04, usa_offset)
    struct_pack("<H", record, 0x06, 3)
    struct_pack("<H", record, usa_offset, 0x0001)
    struct_pack("<H", record, usa_offset + 2, 0x1234)
    struct_pack("<H", record, usa_offset + 4, 0x5678)
    struct_pack("<H", record, 510, 0x0001)
    struct_pack("<H", record, 1022, 0x0001)
    fixed = apply_fixups(bytes(record), sector_size)
    assert fixed[510:512] == b"\x34\x12"
    assert fixed[1022:1024] == b"\x78\x56"


def test_find_max_used_cluster():
    bitmap = bytearray([0b00000101, 0b10000000])
    assert find_max_used_cluster(bytes(bitmap)) == 15


def test_detect_recognises_a_synthetic_ntfs_volume():
    volume = make_ntfs_volume()
    device = FakeDevice(volume)
    from lostpart.fs import ntfs

    result = ntfs.detect(_context(device, 0))
    assert result is not None
    assert result.fs_type == "ntfs"
    assert result.label == "NTFS"
    assert result.confidence > 0.5
    assert result.evidence
    assert result.details["sectors_per_cluster"] == 8


def test_detect_rejects_random_data():
    from lostpart.fs import ntfs

    device = FakeDevice(b"\x5A" * 4096)
    assert ntfs.detect(_context(device, 0)) is None


def test_the_bitmap_matcher_confirms_the_volume_and_its_extent():
    volume = make_ntfs_volume(total_clusters=64, allocated_clusters=32)
    device = FakeDevice(volume)
    boot = parse_boot_sector(make_ntfs_boot_sector(total_sectors=512))
    assert boot is not None

    match = analyse_bitmap(_context(device, 0), boot)
    assert match is not None
    assert match.matched
    assert match.score > 0.9
    # 4 metadata clusters plus 32 data clusters.
    assert match.used_clusters == 36
    assert match.end_sector == 36 * 8
    assert match.evidence


def test_the_bitmap_matcher_rejects_a_volume_whose_data_does_not_match():
    volume = bytearray(make_ntfs_volume(total_clusters=64, allocated_clusters=32))
    # Wipe the data area so it no longer agrees with the bitmap.
    volume[4 * 4096:36 * 4096] = b"\x00" * (32 * 4096)
    device = FakeDevice(bytes(volume))
    boot = parse_boot_sector(make_ntfs_boot_sector(total_sectors=512))
    assert boot is not None

    match = analyse_bitmap(_context(device, 0), boot)
    assert match is not None
    assert not match.matched
    assert match.score < 0.85


def test_mft_records_are_parsed():
    volume = make_ntfs_volume()
    from lostpart.fs.ntfs import NtfsVolume

    device = FakeDevice(volume)
    boot = parse_boot_sector(make_ntfs_boot_sector(total_sectors=512))
    assert boot is not None
    volume_reader = NtfsVolume(_context(device, 0), boot)
    record = volume_reader.read_mft_record(0)
    assert record is not None
    assert record.record_number == 0
    assert record.in_use
    data = record.find(0x80)
    assert data is not None
    assert data.non_resident
    assert data.runlist == ((2, 1),)


def test_the_bitmap_meta_file_can_be_read():
    volume = make_ntfs_volume()
    from lostpart.fs.ntfs import NtfsVolume

    device = FakeDevice(volume)
    boot = parse_boot_sector(make_ntfs_boot_sector(total_sectors=512))
    assert boot is not None
    volume_reader = NtfsVolume(_context(device, 0), boot)
    bitmap = volume_reader.read_bitmap()
    assert bitmap is not None
    assert len(bitmap) == 8
    assert bitmap[0] & 0x0F == 0x0F
