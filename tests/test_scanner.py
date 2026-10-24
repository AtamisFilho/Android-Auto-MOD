"""End to end tests: scan a disk image and write the partition entry back."""

from __future__ import annotations

import json

from lostpart.recover.backup import create_backup, load_backup, restore_backup
from lostpart.recover.writer import recover_partition, validate_candidate
from lostpart.scan.model import LostPartitionCandidate
from lostpart.scan.scanner import Scanner, scan_disk
from lostpart.tables.table import load_partition_table

from .fixtures import FakeDevice, make_disk_with_ntfs, make_gpt_disk, make_mbr, mbr_entry


def test_the_scanner_finds_an_ntfs_volume_in_the_free_space():
    disk = make_disk_with_ntfs(total_sectors=8192, volume_start=4096)
    device = FakeDevice(disk)
    table = load_partition_table(device)
    assert table is not None

    result = scan_disk(device, table)
    assert result.candidates, "the scanner did not find the NTFS volume"
    candidate = result.candidates[0]
    assert candidate.fs_type == "ntfs"
    assert candidate.start_sector == 4096
    assert candidate.confidence > 0.5
    assert "allocation bitmap" in candidate.source


def test_the_scanner_ignores_a_volume_that_is_already_partitioned():
    disk = make_disk_with_ntfs(total_sectors=8192, volume_start=2048)
    device = FakeDevice(disk)
    table = load_partition_table(device)
    assert table is not None
    result = scan_disk(device, table)
    # The volume at 2048 is covered by the MBR entry, so it is not free space.
    assert all(candidate.start_sector != 2048 for candidate in result.candidates)


def test_recover_writes_nothing_in_dry_run_mode():
    disk = make_disk_with_ntfs(total_sectors=8192, volume_start=4096)
    device = FakeDevice(disk)
    table = load_partition_table(device)
    candidate = LostPartitionCandidate(
        start_sector=4096, sector_count=256, fs_type="ntfs", label="NTFS", confidence=0.9
    )
    before = bytes(device.buffer)
    outcome = recover_partition(device, candidate, table, dry_run=True)
    assert outcome.success
    assert "would write" in outcome.message
    assert bytes(device.buffer) == before
    assert device.writes == []


def test_recover_writes_an_mbr_entry():
    disk = bytearray(make_disk_with_ntfs(total_sectors=8192, volume_start=4096))
    device = FakeDevice(bytes(disk))
    table = load_partition_table(device)
    candidate = LostPartitionCandidate(
        start_sector=4096, sector_count=256, fs_type="ntfs", label="NTFS", confidence=0.9
    )
    outcome = recover_partition(device, candidate, table, dry_run=False)
    assert outcome.success
    assert outcome.table_type == "mbr"
    assert device.writes

    # Reload the table and check that the entry is there.
    table2 = load_partition_table(device)
    assert table2 is not None
    starts = [entry.start_lba for entry in table2.occupied]
    assert 4096 in starts
    matching = [e for e in table2.occupied if e.start_lba == 4096][0]
    assert matching.sector_count == 256
    assert matching.raw_type_byte == 0x07


def test_recover_writes_a_gpt_entry_and_updates_the_backup():
    disk = make_gpt_disk(total_sectors=2048)
    device = FakeDevice(disk)
    table = load_partition_table(device)
    assert table is not None
    candidate = LostPartitionCandidate(
        start_sector=64, sector_count=128, fs_type="ntfs", label="NTFS", confidence=0.9
    )
    outcome = recover_partition(device, candidate, table, dry_run=False)
    assert outcome.success
    assert outcome.table_type == "gpt"

    table2 = load_partition_table(device)
    assert table2 is not None
    assert table2.header_crc_valid
    assert table2.entry_array_crc_valid
    starts = [entry.start_lba for entry in table2.occupied]
    assert 64 in starts
    matching = [e for e in table2.occupied if e.start_lba == 64][0]
    assert matching.sector_count == 128
    assert matching.type_code == "{EBD0A0A2-B9E5-4433-87C0-68B6B72699C7}"


def test_recover_refuses_a_candidate_that_overlaps_an_existing_partition():
    disk = make_disk_with_ntfs(total_sectors=8192, volume_start=4096)
    device = FakeDevice(disk)
    table = load_partition_table(device)
    candidate = LostPartitionCandidate(
        start_sector=2048, sector_count=256, fs_type="ntfs", label="NTFS", confidence=0.9
    )
    try:
        validate_candidate(device, table, candidate)
    except Exception as exc:
        assert "overlaps" in str(exc)
    else:  # pragma: no cover - the call must fail
        raise AssertionError("the overlapping candidate was accepted")


def test_recover_refuses_a_candidate_without_a_size():
    disk = make_disk_with_ntfs(total_sectors=8192, volume_start=4096)
    device = FakeDevice(disk)
    table = load_partition_table(device)
    candidate = LostPartitionCandidate(
        start_sector=4096, sector_count=0, fs_type="ntfs", label="NTFS", confidence=0.9
    )
    try:
        validate_candidate(device, table, candidate)
    except Exception as exc:
        assert "size" in str(exc)
    else:  # pragma: no cover - the call must fail
        raise AssertionError("the candidate without a size was accepted")


def test_a_backup_can_be_created_and_restored(tmp_path):
    disk = make_disk_with_ntfs(total_sectors=8192, volume_start=4096)
    device = FakeDevice(disk)
    table = load_partition_table(device)

    # The backup is taken before the write, so it holds the original table.
    backup_path = tmp_path / "backup.json"
    backup = create_backup(device, table, backup_path, device_id="test")
    assert backup_path.exists()

    candidate = LostPartitionCandidate(
        start_sector=4096, sector_count=256, fs_type="ntfs", label="NTFS", confidence=0.9
    )
    recover_partition(device, candidate, table, dry_run=False)
    table_after = load_partition_table(device)
    assert 4096 in [entry.start_lba for entry in table_after.occupied]

    # Restoring the backup brings the original table back.
    restore_backup(device, load_backup(backup_path))
    table2 = load_partition_table(device)
    assert table2 is not None
    starts = [entry.start_lba for entry in table2.occupied]
    assert 4096 not in starts


def test_the_cli_lists_a_disk_image(tmp_path, capsys):
    from lostpart.cli import main

    image = tmp_path / "disk.img"
    image.write_bytes(make_disk_with_ntfs(total_sectors=8192, volume_start=4096))
    assert main(["list", "--device", str(image)]) == 0
    out = capsys.readouterr().out
    assert "MBR" in out
    assert "NTFS" in out


def test_the_cli_scans_a_disk_image(tmp_path, capsys):
    from lostpart.cli import main

    image = tmp_path / "disk.img"
    image.write_bytes(make_disk_with_ntfs(total_sectors=8192, volume_start=4096))
    assert main(["scan", "--device", str(image), "--json", "--quiet"]) == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["candidates"]
    assert payload["candidates"][0]["fs_type"] == "ntfs"
    assert payload["candidates"][0]["start_sector"] == 4096
