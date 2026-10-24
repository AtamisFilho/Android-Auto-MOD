"""Data model shared by the scanner, the recovery writer and the CLI."""

from __future__ import annotations

from dataclasses import dataclass, field

from .unallocated import UnallocatedRegion

__all__ = ["LostPartitionCandidate", "ScanResult", "RecoveryOutcome"]


@dataclass
class LostPartitionCandidate:
    """A filesystem found in free space that has no partition entry."""

    start_sector: int
    sector_count: int
    fs_type: str
    label: str
    confidence: float
    source: str = "boot sector"
    evidence: tuple[str, ...] = ()
    details: dict[str, object] = field(default_factory=dict)
    volume_name: str = ""

    @property
    def end_sector(self) -> int:
        """First sector after the partition."""
        return self.start_sector + self.sector_count

    @property
    def size_bytes(self) -> int:
        return self.sector_count

    def to_dict(self) -> dict[str, object]:
        return {
            "start_sector": self.start_sector,
            "sector_count": self.sector_count,
            "end_sector": self.end_sector,
            "size_bytes": self.size_bytes,
            "fs_type": self.fs_type,
            "label": self.label,
            "volume_name": self.volume_name,
            "confidence": round(self.confidence, 4),
            "source": self.source,
            "evidence": list(self.evidence),
            "details": dict(self.details),
        }


@dataclass
class ScanResult:
    """The outcome of a scan over a disk."""

    device: str
    table_type: str
    mode: str
    candidates: list[LostPartitionCandidate] = field(default_factory=list)
    regions: list[UnallocatedRegion] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    bytes_scanned: int = 0
    cancelled: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "device": self.device,
            "table_type": self.table_type,
            "mode": self.mode,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "bytes_scanned": self.bytes_scanned,
            "cancelled": self.cancelled,
            "regions": [
                {
                    "start_sector": r.start_sector,
                    "sector_count": r.sector_count,
                }
                for r in self.regions
            ],
            "candidates": [c.to_dict() for c in self.candidates],
        }


@dataclass
class RecoveryOutcome:
    """The result of writing one partition entry back to the disk."""

    candidate: LostPartitionCandidate
    success: bool
    message: str
    table_type: str = ""
    partition_index: int | None = None
    backup_path: str | None = None
    written_bytes: int = 0
