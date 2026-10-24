"""Scanning of free space for filesystems that lost their partition entry."""

from __future__ import annotations

from .checkpoint import ScanCheckpoint
from .model import LostPartitionCandidate, RecoveryOutcome, ScanResult
from .scanner import SCAN_MODE_FULL, SCAN_MODE_QUICK, Scanner, scan_disk
from .unallocated import UnallocatedRegion, compute_unallocated_regions

__all__ = [
    "Scanner",
    "scan_disk",
    "SCAN_MODE_QUICK",
    "SCAN_MODE_FULL",
    "ScanResult",
    "LostPartitionCandidate",
    "RecoveryOutcome",
    "UnallocatedRegion",
    "compute_unallocated_regions",
    "ScanCheckpoint",
]
