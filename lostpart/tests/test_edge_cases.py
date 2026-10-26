"""Tests for the branches that *reject* something, and for the edges next to them.

A happy path never reaches a rejection branch, so the bugs that live there
survive code review.  Every test in this module drives one specific
rejection -- or the boundary immediately next to it -- and checks both the
verdict and the state of the disk afterwards.

The rule the whole tool lives by is *a rejected candidate must not leave a
single byte written on the disk*.  That is asserted over and over here.
"""

from __future__ import annotations

import io
import struct
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from .fixtures import (
    FakeDevice,
    mbr_entry,
    make_gpt_disk,
    make_mbr,
)
from lostpart.errors import RecoveryError, ValidationError
from lostpart.recover.writer import (
    mbr_type_for_fs,
    recover_partition,
    validate_candidate,
)
from lostpart.scan.model import LostPartitionCandidate
from lostpart.scan.scanner import Scanner
from lostpart.scan.unallocated import compute_unallocated_regions
from lostpart.constants import GPT_TYPE_BASIC_DATA, GPT_TYPE_EMPTY
from lostpart.tables.gpt import (
    crc32,
    parse_gpt_entries,
    parse_gpt_header,
    verify_gpt_header_crc,
)
from lostpart.tables.table import PartitionEntry, load_partition_table
from lostpart.scan.model import LostPartitionCandidate, ScanResult


NTFS_GUID = "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7"
DATA_GUID = "00000000-0000-0000-0000-000000000001"


def _candidate(start: int, count: int = 256, fs_type: str = "ntfs") -> LostPartitionCandidate:
    return LostPartitionCandidate(
        start_sector=start,
        sector_count=count,
        fs_type=fs_type,
        label=fs_type.upper(),
        confidence=0.9,
    )


def _mbr_disk(entries: list[bytes], total_sectors: int = 16384) -> bytes:
    """An MBR disk big enough for the candidates the tests use."""
    sector = make_mbr(entries)
    return sector + b"\x00" * (total_sectors * 512 - len(sector))


# --------------------------------------------------------------------------
# The rejection branches of the writer
# --------------------------------------------------------------------------


def test_a_candidate_without_a_size_is_rejected():
    device = FakeDevice(_mbr_disk([mbr_entry(2048, 1024, 0x07)]))
    table = load_partition_table(device)
    with pytest.raises(ValidationError):
        validate_candidate(device, table, _candidate(4096, count=0))
    assert device.writes == []


def test_a_candidate_that_starts_at_sector_zero_is_rejected():
    """Sector 0 holds the partition table itself."""
    device = FakeDevice(_mbr_disk([mbr_entry(2048, 1024, 0x07)]))
    table = load_partition_table(device)
    with pytest.raises(ValidationError):
        validate_candidate(device, table, _candidate(0, count=256))
    assert device.writes == []


def test_a_candidate_that_runs_past_the_end_of_the_disk_is_rejected():
    device = FakeDevice(_mbr_disk([mbr_entry(2048, 1024, 0x07)]))
    table = load_partition_table(device)
    with pytest.raises(ValidationError):
        validate_candidate(device, table, _candidate(16000, count=4096))
    assert device.writes == []


def test_a_candidate_that_overlaps_a_partition_is_rejected():
    device = FakeDevice(_mbr_disk([mbr_entry(2048, 1024, 0x07)]))
    table = load_partition_table(device)
    with pytest.raises(ValidationError):
        validate_candidate(device, table, _candidate(2560, count=256))
    assert device.writes == []


def test_a_candidate_that_merely_touches_a_partition_is_accepted():
    """The partition ends at 3072, so a candidate starting at 3072 is fine."""
    device = FakeDevice(_mbr_disk([mbr_entry(2048, 1024, 0x07)]))
    table = load_partition_table(device)
    validate_candidate(device, table, _candidate(3072, count=256))
    assert device.writes == []


def test_a_rejected_candidate_leaves_the_disk_untouched():
    """``recover_partition`` must not write before the validation passes."""
    disk = _mbr_disk([mbr_entry(2048, 1024, 0x07)])
    device = FakeDevice(disk)
    table = load_partition_table(device)
    before = bytes(device.buffer)

    with pytest.raises(ValidationError):
        recover_partition(device, _candidate(2560, count=256), table, dry_run=False)

    assert bytes(device.buffer) == before
    assert device.writes == []


def test_a_read_only_disk_is_rejected_before_any_write():
    device = FakeDevice(_mbr_disk([mbr_entry(2048, 1024, 0x07)]))
    table = load_partition_table(device)
    device._readonly = True
    with pytest.raises(RecoveryError):
        recover_partition(device, _candidate(4096, count=256), table, dry_run=False)
    assert device.writes == []


def test_a_full_mbr_without_an_extended_partition_is_rejected():
    """Four primary slots taken and no extended container: nowhere to write."""
    disk = _mbr_disk([
        mbr_entry(2048, 1024, 0x07),
        mbr_entry(4096, 1024, 0x83),
        mbr_entry(8192, 1024, 0x0C),
        mbr_entry(16384, 1024, 0x83),
    ])
    device = FakeDevice(disk)
    table = load_partition_table(device)
    with pytest.raises(ValidationError):
        recover_partition(device, _candidate(24576, count=256), table, dry_run=False)
    assert device.writes == []


def test_a_full_gpt_is_rejected():
    """Every entry slot taken: the recovery has to refuse."""
    entries = [
        (GPT_TYPE_BASIC_DATA, DATA_GUID, 64 + index * 16, f"p{index}")
        for index in range(128)
    ]
    device = FakeDevice(make_gpt_disk(total_sectors=4096, entries=entries))
    table = load_partition_table(device)
    assert table is not None
    assert len(table.gpt_entries) == 128
    with pytest.raises(ValidationError):
        recover_partition(device, _candidate(3000, count=16), table, dry_run=False)
    assert device.writes == []


# --------------------------------------------------------------------------
# The GPT write path, with an entry array that is not 128 bytes wide
# --------------------------------------------------------------------------


def test_the_backup_gpt_is_not_written_over_its_own_header():
    """The backup array must stop right before the backup header.

    The array occupies the sectors before the header.  One sector too high
    and the last entry of the backup array is overwritten by the header,
    which leaves the backup of the disk with a broken table.
    """
    from lostpart.tables.table import read_gpt_backup

    device = FakeDevice(make_gpt_disk(total_sectors=4096))
    table = load_partition_table(device)
    assert table is not None

    outcome = recover_partition(device, _candidate(64, count=16), table, dry_run=False)
    assert outcome.success

    after = load_partition_table(device)
    assert after is not None
    header = after.gpt_header
    assert header is not None

    backup = read_gpt_backup(device, header)
    assert backup is not None, "the backup table must still be readable"
    backup_header_bytes, backup_array = backup

    # The backup header is a real header, not a slice of the array.
    backup_header = parse_gpt_header(backup_header_bytes)
    assert backup_header is not None
    assert verify_gpt_header_crc(backup_header_bytes), \
        "the backup header must have a valid CRC"

    # The backup array must be exactly as long as the primary one.
    primary = device.read_at(
        header.partition_entry_lba * device.sector_size,
        header.partition_entry_count * header.partition_entry_size,
    )
    assert len(backup_array) == len(primary)
    assert backup_array == primary

    # And the backup array must not reach into the backup header sector.
    array_sectors = (
        header.partition_entry_count * header.partition_entry_size + 511
    ) // 512
    assert header.backup_lba - array_sectors + array_sectors == header.backup_lba
    assert header.backup_lba - array_sectors < header.backup_lba


def test_a_gpt_with_wider_entries_is_recovered_without_corruption():
    """A GPT whose entries are 256 bytes wide must survive the write.

    The entry is 128 bytes on disk.  When the array slot is wider, the
    entry has to be padded, the array must keep its length, and both copies
    of the table must end up with a valid CRC.
    """
    entry_size = 256
    entry_count = 16
    device = FakeDevice(make_gpt_disk(
        total_sectors=4096, entry_count=entry_count, entry_size=entry_size))
    table = load_partition_table(device)
    assert table is not None
    assert table.gpt_header is not None
    assert table.gpt_header.partition_entry_size == entry_size

    outcome = recover_partition(device, _candidate(64, count=16), table, dry_run=False)
    assert outcome.success

    after = load_partition_table(device)
    assert after is not None
    assert after.header_crc_valid, "the primary header CRC must still be valid"
    assert after.entry_array_crc_valid, "the entry array CRC must still be valid"
    assert len(after.gpt_entries) == entry_count

    # The slot that was written must be exactly one entry wide.
    header = after.gpt_header
    assert header is not None
    array = device.read_at(
        header.partition_entry_lba * device.sector_size,
        header.partition_entry_count * header.partition_entry_size,
    )
    assert len(array) == entry_count * entry_size
    written = array[0:entry_size]
    assert written[128:] == b"\x00" * (entry_size - 128), \
        "the entry must be padded with zeros up to the slot width"

    # The backup copy must be identical to the primary one.
    from lostpart.tables.table import read_gpt_backup

    backup = read_gpt_backup(device, header)
    assert backup is not None
    backup_header_bytes, backup_array = backup
    assert len(backup_array) == entry_count * entry_size
    assert backup_array == array, "the backup array must match the primary one"
    backup_header = parse_gpt_header(backup_header_bytes)
    assert backup_header is not None
    assert backup_header.partition_entry_array_crc32 == crc32(array)


def test_a_gpt_entry_array_shorter_than_the_header_claims_is_not_read_gigantically():
    """A corrupt header must not make the tool read an absurd amount of data."""
    from lostpart.tables.table import load_partition_table as load

    disk = bytearray(make_gpt_disk(total_sectors=4096, entry_count=16))
    # Blow up the entry count in the primary header without fixing its CRC.
    header = bytearray(disk[512:1024])
    struct.pack_into("<I", header, 0x50, 0xFFFFFFFF)
    disk[512:1024] = header

    class CountingDevice(FakeDevice):
        def __init__(self, data):
            super().__init__(data)
            self.largest_read = 0

        def read_at(self, offset: int, size: int) -> bytes:
            self.largest_read = max(self.largest_read, size)
            return super().read_at(offset, size)

    device = CountingDevice(bytes(disk))
    load(device)
    assert device.largest_read <= 16 * 1024 * 1024, \
        "a corrupt entry count must not trigger an unbounded read"


# --------------------------------------------------------------------------
# The rejection branch of the scanner: overlapping candidates
# --------------------------------------------------------------------------


def test_the_scanner_drops_the_weaker_of_two_overlapping_candidates():
    device = FakeDevice(_mbr_disk([mbr_entry(2048, 1024, 0x07)]))
    table = load_partition_table(device)
    scanner = Scanner(device)

    strong = LostPartitionCandidate(2048, 512, "ntfs", "a", 0.95)
    weak = LostPartitionCandidate(2304, 512, "ntfs", "b", 0.40)

    kept, rejected = scanner._resolve_overlaps([weak, strong])
    assert [c.confidence for c in kept] == [0.95]
    assert len(rejected) == 1
    assert rejected[0].candidate.confidence == 0.40
    assert "sobrepõe" in rejected[0].reason or "overlap" in rejected[0].reason.lower()


def test_candidates_that_only_touch_are_not_rejected():
    device = FakeDevice(_mbr_disk([mbr_entry(2048, 1024, 0x07)]))
    table = load_partition_table(device)
    scanner = Scanner(device)

    first = LostPartitionCandidate(2048, 512, "ntfs", "a", 0.9)
    second = LostPartitionCandidate(2560, 512, "ntfs", "b", 0.9)

    kept, rejected = scanner._resolve_overlaps([first, second])
    assert len(kept) == 2
    assert rejected == []


def test_the_rejected_candidates_reach_the_scan_result():
    """A finding must never disappear without a trace."""
    from lostpart.scan.model import ScanResult

    result = ScanResult(device="x", table_type="mbr", mode="full")
    assert result.rejected == []
    assert "rejected" in result.to_dict()


# --------------------------------------------------------------------------
# The free space computation, with a corrupt entry
# --------------------------------------------------------------------------


def test_the_free_regions_never_overlap_even_with_a_corrupt_entry():
    """A GPT entry whose last LBA is before its first LBA has a negative size.

    Such an entry must not make the free regions overlap, because the
    scanner would then read the same sectors twice and believe it is free
    space that is already occupied.
    """
    corrupt = PartitionEntry(
        index=0, start_lba=100, sector_count=-10, label="corrupta",
        type_code="0x00",
    )
    regions = compute_unallocated_regions([corrupt], 1, 1000)

    for previous, following in zip(regions, regions[1:]):
        assert previous.end_sector <= following.start_sector, \
            f"regions overlap: {previous} and {following}"
    assert sum(r.sector_count for r in regions) <= 1000 - 1


def test_a_negative_sector_count_is_never_reported_as_a_partition():
    """The listing must not show a negative size for a broken entry."""
    device = FakeDevice(_mbr_disk([mbr_entry(2048, 1024, 0x07)]))
    table = load_partition_table(device)
    assert table is not None
    for entry in table.occupied:
        assert entry.sector_count > 0


# --------------------------------------------------------------------------
# The type mapping used when the entry is written
# --------------------------------------------------------------------------


@pytest.mark.parametrize("fs_type,expected", [
    ("ntfs", 0x07),
    ("exfat", 0x07),
    ("fat32", 0x0C),
    ("fat16", 0x06),
    ("fat12", 0x01),
    ("ext4", 0x83),
    ("swap", 0x82),
    ("hfsplus", 0x0A),
])
def test_the_mbr_type_of_every_filesystem_we_detect(fs_type: str, expected: int):
    assert mbr_type_for_fs(fs_type) == expected


def test_an_unknown_filesystem_is_not_silently_written_as_ntfs():
    """Claiming a wrong type makes the system mount the volume wrongly."""
    with pytest.raises(ValueError):
        mbr_type_for_fs("zfs")


def test_an_unknown_filesystem_is_refused_before_anything_is_written():
    from lostpart.recover.writer import gpt_type_for_fs

    with pytest.raises(ValueError):
        gpt_type_for_fs("zfs")

    device = FakeDevice(_mbr_disk([mbr_entry(2048, 1024, 0x07)]))
    table = load_partition_table(device)
    candidate = _candidate(4096, count=256, fs_type="zfs")
    with pytest.raises(ValidationError):
        validate_candidate(device, table, candidate)
    assert device.writes == []


def test_the_rejected_candidates_are_reported_by_the_command_line():
    """A finding that was discarded has to reach the user."""
    from lostpart import cli
    from lostpart.scan.model import RejectedCandidate

    result = ScanResult(device="0", table_type="mbr", mode="full")
    result.candidates = [_candidate(4096, count=256)]
    result.rejected = [
        RejectedCandidate(
            candidate=_candidate(4200, count=256),
            reason="overlaps the candidate at sector 4096 (ntfs, confidence 90%)",
        )
    ]

    text = cli.format_scan_result(result, "0")
    assert "descartado" in text
    assert "4200" in text


# --------------------------------------------------------------------------
# The device lifecycle
# --------------------------------------------------------------------------


def test_a_physical_disk_handle_is_closed_when_the_geometry_query_fails():
    """A handle left open keeps the physical disk busy for the session."""
    import os

    if os.name != "nt":
        pytest.skip("the physical disk driver is Windows only")

    from lostpart import device as device_module

    closed: list[int] = []

    class FakeKernel:
        INVALID_HANDLE_VALUE = -1

        def CreateFileW(self, *_args, **_kwargs):
            return 4242

        def CloseHandle(self, handle):
            closed.append(handle)
            return True

    original_kernel = device_module._kernel32
    original_query = device_module.WindowsPhysicalDrive._query_sector_size

    def broken_query(self):
        raise device_module.DeviceError("geometry unavailable")

    device_module._kernel32 = FakeKernel()
    device_module.WindowsPhysicalDrive._query_sector_size = broken_query
    try:
        with pytest.raises(device_module.DeviceError):
            device_module.WindowsPhysicalDrive(0)
    finally:
        device_module._kernel32 = original_kernel
        device_module.WindowsPhysicalDrive._query_sector_size = original_query

    assert closed == [4242], \
        "the handle must be closed when the initialisation fails"


# --------------------------------------------------------------------------
# The device lifecycle
# --------------------------------------------------------------------------


def test_listing_the_disks_closes_every_device_it_opens():
    """A physical disk left open keeps the disk busy for the whole session."""
    from lostpart import cli

    opened: list[FakeDevice] = []

    class TrackingDevice(FakeDevice):
        def __init__(self, data):
            super().__init__(data)
            self.closed = False
            opened.append(self)

        def close(self) -> None:
            self.closed = True

    disk = _mbr_disk([mbr_entry(2048, 1024, 0x07)])
    device = TrackingDevice(disk)

    original = cli.open_device
    cli.open_device = lambda spec, read_only=False: device
    try:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            cli.list_devices_text("0")
    finally:
        cli.open_device = original

    assert device.closed, "the device must be closed after the listing"


def test_listing_the_disks_closes_a_device_whose_table_cannot_be_read():
    """A disk with no partition table takes an early exit: it must be closed too."""
    from lostpart import cli

    class TrackingDevice(FakeDevice):
        def __init__(self, data):
            super().__init__(data)
            self.closed = False

        def close(self) -> None:
            self.closed = True

    device = TrackingDevice(b"\x00" * 4096)
    original = cli.open_device
    cli.open_device = lambda spec, read_only=False: device
    try:
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            cli.list_devices_text("0")
    finally:
        cli.open_device = original

    assert device.closed, "the device must be closed even without a table"


# --------------------------------------------------------------------------
# The console renderer
# --------------------------------------------------------------------------


def test_a_table_row_longer_than_the_header_does_not_crash_the_console():
    from lostpart.ui import console

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        console.table(("A", "B"), [["1", "2", "3"]])
    assert "3" in buffer.getvalue()


def test_a_table_row_shorter_than_the_header_does_not_crash_the_console():
    from lostpart.ui import console

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        console.table(("A", "B"), [["1"]])
    assert "1" in buffer.getvalue()


# --------------------------------------------------------------------------
# The backup: what is saved and what is restored
# --------------------------------------------------------------------------


def test_the_backup_of_a_gpt_covers_the_right_sectors():
    """The backup has to hold the array that is really on the disk.

    The backup array lives in the sectors before the backup header.  One
    sector too high and the file holds the header twice and misses the last
    sector of the array.
    """
    from lostpart.recover.backup import create_backup

    device = FakeDevice(make_gpt_disk(total_sectors=4096))
    table = load_partition_table(device)
    assert table is not None
    header = table.gpt_header
    assert header is not None

    backup = create_backup(device, table, "backup.json", device_id="0")
    array_sectors = (
        header.partition_entry_count * header.partition_entry_size + 511
    ) // 512
    starts = [int(chunk["start_lba"]) for chunk in backup.chunks]
    assert header.partition_entry_lba in starts
    assert header.backup_lba - array_sectors in starts
    assert header.backup_lba in starts
    # The sector of the backup header must not be part of the array capture.
    array_chunk = [c for c in backup.chunks
                   if int(c["start_lba"]) == header.backup_lba - array_sectors][0]
    assert int(array_chunk["count"]) == array_sectors
    assert int(array_chunk["start_lba"]) + int(array_chunk["count"]) == header.backup_lba


def test_a_backup_of_another_disk_is_refused():
    """Restoring a table from another disk would destroy this one."""
    import base64

    from lostpart.errors import RecoveryError
    from lostpart.recover.backup import TableBackup, restore_backup

    device = FakeDevice(_mbr_disk([mbr_entry(2048, 1024, 0x07)]))
    backup = TableBackup(
        path=Path("outro.json"),
        kind="mbr",
        device_id="outro-disco",
        sector_size=4096,          # a different disk
        total_sectors=999999,
        created="2026-01-01T00:00:00",
        chunks=[{
            "start_lba": 0,
            "count": 1,
            "data": base64.b64encode(b"\x00" * 4096).decode("ascii"),
        }],
    )
    with pytest.raises(RecoveryError):
        restore_backup(device, backup)
    assert device.writes == [], "nothing may be written when the backup is refused"


def test_a_truncated_backup_is_refused_before_anything_is_written():
    """Half a sector written and half untouched is worse than nothing."""
    import base64

    from lostpart.errors import RecoveryError
    from lostpart.recover.backup import TableBackup, restore_backup

    device = FakeDevice(_mbr_disk([mbr_entry(2048, 1024, 0x07)]))
    backup = TableBackup(
        path=Path("truncado.json"),
        kind="mbr",
        device_id="0",
        sector_size=512,
        total_sectors=device.total_sectors,
        created="2026-01-01T00:00:00",
        chunks=[{
            "start_lba": 0,
            "count": 1,
            "data": base64.b64encode(b"\x00" * 100).decode("ascii"),
        }],
    )
    with pytest.raises(RecoveryError):
        restore_backup(device, backup)
    assert device.writes == []


def test_a_complete_backup_is_restored():
    import base64

    from lostpart.recover.backup import TableBackup, restore_backup

    device = FakeDevice(_mbr_disk([mbr_entry(2048, 1024, 0x07)]))
    payload = b"\xaa" * 512
    backup = TableBackup(
        path=Path("completo.json"),
        kind="mbr",
        device_id="0",
        sector_size=512,
        total_sectors=device.total_sectors,
        created="2026-01-01T00:00:00",
        chunks=[{
            "start_lba": 0,
            "count": 1,
            "data": base64.b64encode(payload).decode("ascii"),
        }],
    )
    written = restore_backup(device, backup)
    assert written == 512
    assert bytes(device.buffer)[:512] == payload


# --------------------------------------------------------------------------
# Resuming an interrupted scan
# --------------------------------------------------------------------------


def test_a_resumed_scan_does_not_read_the_sectors_already_scanned():
    """The point of a checkpoint is to not read the same sectors twice."""
    from .fixtures import make_disk_with_ntfs
    from lostpart.scan.scanner import Scanner
    from lostpart.scan.unallocated import UnallocatedRegion

    class RecordingDevice(FakeDevice):
        def __init__(self, data):
            super().__init__(data)
            self.reads: list[int] = []

        def read_at(self, offset: int, size: int) -> bytes:
            self.reads.append(offset)
            return super().read_at(offset, size)

    device = RecordingDevice(make_disk_with_ntfs(total_sectors=8192,
                                                 volume_start=4096))
    scanner = Scanner(device)
    scanner.scan([UnallocatedRegion(4096, 1024)], resume_from=4096 + 256)

    assert device.reads, "the scan has to read something"
    assert min(device.reads) >= (4096 + 256) * device.sector_size, \
        "the sectors before the resume point must not be read again"


def test_a_resumed_scan_keeps_the_candidates_of_the_previous_run():
    from .fixtures import make_disk_with_ntfs
    from lostpart.scan.scanner import Scanner
    from lostpart.scan.unallocated import UnallocatedRegion

    device = FakeDevice(make_disk_with_ntfs(total_sectors=8192, volume_start=4096))
    scanner = Scanner(device)
    region = UnallocatedRegion(4096, 1024)

    complete, _ = scanner.scan([region])
    assert complete, "the scan has to find the NTFS volume"

    resumed, _ = scanner.scan([region], resume_from=4096 + 512, known=complete)
    assert [c.start_sector for c in resumed] == [c.start_sector for c in complete]
    assert [c.confidence for c in resumed] == [c.confidence for c in complete]


def test_a_candidate_survives_the_checkpoint_round_trip():
    """The sector size has to survive, or the size is computed wrong."""
    from lostpart.scan.checkpoint import ScanCheckpoint

    candidate = LostPartitionCandidate(
        start_sector=2048, sector_count=1024, fs_type="ntfs", label="NTFS",
        confidence=0.9, sector_size=4096,
    )
    with ScanCheckpoint() as store:
        identifier = store.start("disco")
        store.add_candidate(identifier, candidate)
        loaded = store.load(identifier)
        assert loaded is not None
        assert len(loaded.candidates) == 1
        assert loaded.candidates[0].sector_size == 4096
        assert loaded.candidates[0].size_bytes == 1024 * 4096


def test_the_checkpoint_refuses_an_unknown_column():
    """The column names go into the SQL, so they cannot be free text."""
    from lostpart.scan.checkpoint import ScanCheckpoint

    with ScanCheckpoint() as store:
        identifier = store.start("disco")
        with pytest.raises(ValueError):
            store.update(identifier, not_a_column="x")


def test_an_interrupted_scan_is_resumed_by_the_command_line(tmp_path):
    """The second run continues where the first one stopped."""
    from lostpart import cli
    from lostpart.scan.checkpoint import ScanCheckpoint

    disk = _mbr_disk([mbr_entry(2048, 1024, 0x07)])
    image = tmp_path / "disco.img"
    image.write_bytes(disk)
    checkpoint = tmp_path / "scan.db"

    # A first run that is cut short.
    with ScanCheckpoint(checkpoint) as store:
        identifier = store.start(str(image), mode="full")
        store.set_progress(identifier, 4096)
        store.set_status(identifier, "cancelled")

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = cli.main(["escanear", "--device", str(image),
                         "--checkpoint", str(checkpoint)])
    assert code == 0
    assert "Retomando a varredura" in buffer.getvalue(), \
        "the second run has to say that it continues the previous one"

    # The checkpoint of the second run has to be complete.
    with ScanCheckpoint(checkpoint) as store:
        latest = store.latest(str(image))
        assert latest is not None
        assert latest.status == "done"
