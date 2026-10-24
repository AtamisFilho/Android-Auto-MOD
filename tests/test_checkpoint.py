"""Tests for the resumable scan checkpoint."""

from __future__ import annotations

from lostpart.scan.checkpoint import (
    STATUS_CANCELLED,
    STATUS_DONE,
    ScanCheckpoint,
)
from lostpart.scan.model import LostPartitionCandidate


def _candidate(start: int, count: int = 100) -> LostPartitionCandidate:
    return LostPartitionCandidate(
        start_sector=start,
        sector_count=count,
        fs_type="ntfs",
        label="NTFS",
        confidence=0.87,
        source="boot sector + allocation bitmap",
        evidence=("NTFS OEM identifier present",),
        details={"bytes_per_sector": 512},
        volume_name="System",
    )


def test_a_checkpoint_records_the_found_partitions(tmp_path):
    path = tmp_path / "scan.db"
    with ScanCheckpoint(path) as checkpoint:
        session = checkpoint.start(device_id=r"\\.\PhysicalDrive0", mode="full")
        checkpoint.add_candidate(session, _candidate(4096))
        checkpoint.add_candidate(session, _candidate(8192, 200))
        checkpoint.set_status(session, STATUS_DONE)

        loaded = checkpoint.load(session)
        assert loaded is not None
        assert loaded.status == STATUS_DONE
        assert len(loaded.candidates) == 2
        assert loaded.candidates[0].start_sector == 4096
        assert loaded.candidates[0].fs_type == "ntfs"
        assert loaded.candidates[0].volume_name == "System"
        assert loaded.candidates[1].sector_count == 200


def test_the_latest_checkpoint_is_found(tmp_path):
    with ScanCheckpoint(tmp_path / "scan.db") as checkpoint:
        first = checkpoint.start(device_id="disk0")
        checkpoint.add_candidate(first, _candidate(100))
        second = checkpoint.start(device_id="disk0")
        checkpoint.add_candidate(second, _candidate(200))

        latest = checkpoint.latest("disk0")
        assert latest is not None
        assert latest.id == second
        assert latest.candidates[0].start_sector == 200


def test_the_progress_sector_is_stored(tmp_path):
    with ScanCheckpoint(tmp_path / "scan.db") as checkpoint:
        session = checkpoint.start(device_id="disk0")
        checkpoint.set_progress(session, 123456)
        loaded = checkpoint.load(session)
        assert loaded is not None
        assert loaded.last_sector == 123456


def test_a_cancelled_scan_is_marked(tmp_path):
    with ScanCheckpoint(tmp_path / "scan.db") as checkpoint:
        session = checkpoint.start(device_id="disk0")
        checkpoint.set_status(session, STATUS_CANCELLED)
        loaded = checkpoint.load(session)
        assert loaded is not None
        assert loaded.status == STATUS_CANCELLED
        assert loaded.finished


def test_the_checkpoint_survives_a_reopen(tmp_path):
    path = tmp_path / "scan.db"
    with ScanCheckpoint(path) as checkpoint:
        session = checkpoint.start(device_id="disk0")
        checkpoint.add_candidate(session, _candidate(4096))
    with ScanCheckpoint(path) as checkpoint:
        loaded = checkpoint.latest("disk0")
        assert loaded is not None
        assert loaded.candidates[0].start_sector == 4096
